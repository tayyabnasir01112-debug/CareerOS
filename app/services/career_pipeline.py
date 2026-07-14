from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.schemas.evaluation import EvaluationRunOptions
from app.schemas.notification import (
    CareerPipelineSummary,
    NotificationRunSummary,
    PipelineRunOptions,
)
from app.schemas.pipeline import CollectionSummary, CollectorPlatform
from app.services.collection import collect_configured_jobs
from app.services.evaluation_orchestrator import run_configured_evaluations
from app.services.evaluation_provider import RecruiterEvaluationProvider
from app.services.notification import (
    DiscordNotificationService,
    DiscordWebhookProvider,
    NotificationProvider,
    NotificationRepository,
)

CollectionRunner = Callable[
    [AsyncSession, Settings, CollectorPlatform | None], Awaitable[CollectionSummary]
]


async def _default_collection_runner(
    session: AsyncSession,
    settings: Settings,
    source: CollectorPlatform | None,
) -> CollectionSummary:
    return await collect_configured_jobs(session, settings, source=source)


class CareerPipelineOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        evaluation_provider: RecruiterEvaluationProvider | None = None,
        notification_provider: NotificationProvider | None = None,
        collection_runner: CollectionRunner = _default_collection_runner,
    ) -> None:
        self.session = session
        self.settings = settings
        self.evaluation_provider = evaluation_provider
        self.notification_provider = notification_provider
        self.collection_runner = collection_runner

    async def run(self, options: PipelineRunOptions) -> CareerPipelineSummary:
        source = None if options.all_sources else options.source
        collection = await self.collection_runner(self.session, self.settings, source)
        evaluation = await run_configured_evaluations(
            self.session,
            self.settings,
            EvaluationRunOptions(
                limit=options.limit,
                force=options.force_evaluation,
                dry_run=options.dry_run,
            ),
            provider=self.evaluation_provider,
        )
        notifications = await self._notify(options)
        return CareerPipelineSummary(
            jobs_fetched=collection.jobs_fetched,
            jobs_inserted=collection.jobs_inserted,
            jobs_updated=collection.jobs_updated,
            duplicates_skipped=collection.duplicates_skipped,
            jobs_eligible=collection.jobs_eligible + collection.jobs_flagged,
            jobs_evaluated=evaluation.evaluations_completed,
            cached_evaluations_reused=evaluation.cached_evaluations_reused,
            evaluations_failed=evaluation.failed_evaluations,
            notifications_sent=notifications.notifications_sent,
            notifications_skipped=notifications.notifications_skipped,
            notification_failures=notifications.notification_failures,
            total_input_tokens=evaluation.total_input_tokens,
            total_output_tokens=evaluation.total_output_tokens,
            daily_evaluation_budget_remaining=evaluation.daily_budget_remaining,
            errors=[*collection.errors, *evaluation.errors, *notifications.errors],
            notification_suppression_reasons=notifications.suppression_reasons,
        )

    async def _notify(self, options: PipelineRunOptions) -> NotificationRunSummary:
        limit = self.settings.discord_max_notifications_per_run
        repository = NotificationRepository(self.session)
        if options.no_notify or options.dry_run or not self.settings.discord_notifications_enabled:
            candidates = await repository.candidates(
                minimum_score=self.settings.discord_minimum_match_score,
                limit=limit,
                notify_consider=self.settings.discord_notify_consider,
                require_confirmed_location=self.settings.discord_require_confirmed_location,
            )
            return NotificationRunSummary(notifications_skipped=len(candidates))

        owned_provider: DiscordWebhookProvider | None = None
        provider = self.notification_provider
        if provider is None:
            webhook = self.settings.discord_webhook_value()
            if webhook is None:
                candidates = await repository.candidates(
                    minimum_score=self.settings.discord_minimum_match_score,
                    limit=limit,
                    notify_consider=self.settings.discord_notify_consider,
                    require_confirmed_location=self.settings.discord_require_confirmed_location,
                )
                return NotificationRunSummary(
                    notifications_skipped=len(candidates),
                    errors=["configuration_error: Discord webhook is not configured"],
                )
            owned_provider = DiscordWebhookProvider(
                webhook,
                timeout_seconds=self.settings.discord_request_timeout_seconds,
                max_retries=self.settings.discord_max_retries,
                retry_base_seconds=self.settings.discord_retry_base_seconds,
            )
            provider = owned_provider
        try:
            return await DiscordNotificationService(self.session, provider).run(
                minimum_score=self.settings.discord_minimum_match_score,
                limit=limit,
                notify_consider=self.settings.discord_notify_consider,
                require_confirmed_location=self.settings.discord_require_confirmed_location,
            )
        finally:
            if owned_provider is not None:
                await owned_provider.close()


async def run_career_pipeline(
    session: AsyncSession,
    settings: Settings,
    options: PipelineRunOptions,
    *,
    evaluation_provider: RecruiterEvaluationProvider | None = None,
    notification_provider: NotificationProvider | None = None,
    collection_runner: CollectionRunner = _default_collection_runner,
) -> CareerPipelineSummary:
    return await CareerPipelineOrchestrator(
        session,
        settings,
        evaluation_provider=evaluation_provider,
        notification_provider=notification_provider,
        collection_runner=collection_runner,
    ).run(options)
