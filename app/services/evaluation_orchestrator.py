import time
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import redact_sensitive_text
from app.db.models import EligibilityStatus, Job
from app.schemas.configuration import CandidateProfile, JobPreferences
from app.schemas.evaluation import (
    CompensationAssessment,
    DryRunEvaluation,
    EvaluationErrorCategory,
    EvaluationRunOptions,
    EvaluationRunSummary,
    LocationAssessment,
    Recommendation,
    RecruiterEvaluationResult,
    RoleCategory,
    SeniorityAssessment,
)
from app.services.configuration import load_candidate_profile, load_job_preferences
from app.services.evaluation_input import (
    EvaluationInputBuilder,
    EvaluationInputError,
)
from app.services.evaluation_provider import (
    OpenAIRecruiterEvaluationProvider,
    ProviderFailure,
    RecruiterEvaluationProvider,
    RecruiterEvaluator,
)
from app.services.evaluation_repository import EvaluationRepository


class EvaluationOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        candidate_profile: CandidateProfile,
        preferences: JobPreferences,
        provider: RecruiterEvaluationProvider | None,
        *,
        now: datetime | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.candidate_profile = candidate_profile
        self.preferences = preferences
        self.repository = EvaluationRepository(session)
        self.builder = EvaluationInputBuilder(
            maximum_characters=settings.openai_max_input_characters,
            model=settings.openai_model_label(),
        )
        self.evaluator = (
            RecruiterEvaluator(
                provider,
                max_retries=settings.openai_max_retries,
                retry_base_seconds=settings.openai_retry_base_seconds,
            )
            if provider is not None
            else None
        )
        self.now = (now or datetime.now(UTC)).astimezone(UTC)

    async def run(self, options: EvaluationRunOptions) -> EvaluationRunSummary:
        daily_used = await self.repository.count_daily_requests(self.now)
        summary = EvaluationRunSummary(
            daily_budget_remaining=max(0, self.settings.openai_max_evaluations_per_day - daily_used)
        )
        selection_limit = options.limit or self.settings.openai_max_evaluations_per_run
        jobs = await self.repository.select_jobs(job_id=options.job_id, limit=selection_limit)
        requested_this_run = 0

        for job in jobs:
            summary.jobs_considered += 1
            if not self._has_sufficient_current_content(job):
                summary.skipped_by_score_or_status_rules += 1
                continue
            try:
                prepared = self.builder.build(job, self.candidate_profile, self.preferences)
            except EvaluationInputError as exc:
                summary.failed_evaluations += 1
                summary.errors.append(
                    f"job {job.id}: {EvaluationErrorCategory.INPUT_TOO_LARGE.value}: "
                    f"{redact_sensitive_text(str(exc))}"
                )
                continue

            rule_score = self.builder.rule_score(job.eligibility_status)
            if job.eligibility_status == EligibilityStatus.REJECTED:
                summary.skipped_by_deterministic_eligibility += 1
                if not options.dry_run:
                    await self.repository.save_ineligible(prepared, self._ineligible_result(job))
                    await self.session.commit()
                continue
            if job.eligibility_status == EligibilityStatus.PENDING or (
                rule_score < options.minimum_rule_score
            ):
                summary.skipped_by_score_or_status_rules += 1
                continue

            cached = None if options.force else await self.repository.find_cached(prepared)
            if cached is not None:
                summary.cached_evaluations_reused += 1

            if options.dry_run:
                summary.dry_run_inputs.append(
                    DryRunEvaluation(
                        job_id=job.id,
                        input_hash=prepared.input_hash,
                        job_content_fingerprint=prepared.job_content_fingerprint,
                        truncated=prepared.truncated,
                    )
                )
                continue
            if cached is not None:
                continue
            if requested_this_run >= self.settings.openai_max_evaluations_per_run:
                summary.skipped_by_score_or_status_rules += 1
                continue
            if daily_used + requested_this_run >= self.settings.openai_max_evaluations_per_day:
                summary.skipped_by_score_or_status_rules += 1
                continue
            if self.evaluator is None:
                summary.failed_evaluations += 1
                summary.errors.append(
                    f"job {job.id}: {EvaluationErrorCategory.CONFIGURATION_ERROR.value}: "
                    "OpenAI provider is not configured"
                )
                break

            requested_this_run += 1
            summary.evaluations_requested += 1
            started = time.perf_counter()
            try:
                provider_result = await self.evaluator.evaluate(prepared)
            except ProviderFailure as exc:
                duration_ms = int((time.perf_counter() - started) * 1000)
                summary.failed_evaluations += 1
                safe_summary = redact_sensitive_text(str(exc))[:500]
                summary.errors.append(f"job {job.id}: {exc.category.value}: {safe_summary}")
                await self.repository.save_failure(
                    prepared, exc.category, safe_summary, duration_ms
                )
                await self.session.commit()
                if exc.fatal:
                    break
                continue

            duration_ms = int((time.perf_counter() - started) * 1000)
            await self.repository.save_success(prepared, provider_result, duration_ms)
            await self.session.commit()
            summary.evaluations_completed += 1
            summary.total_input_tokens += provider_result.input_tokens or 0
            summary.total_output_tokens += provider_result.output_tokens or 0

        summary.daily_budget_remaining = max(
            0,
            self.settings.openai_max_evaluations_per_day - daily_used - requested_this_run,
        )
        return summary

    def _has_sufficient_current_content(self, job: Job) -> bool:
        if len(job.title.strip()) < 3 or len(job.description.strip()) < 80:
            return False
        published = job.published_at or job.source_updated_at
        if published is None:
            return True
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        age_hours = (self.now - published.astimezone(UTC)).total_seconds() / 3600
        return age_hours <= self.preferences.maximum_listing_age_hours

    @staticmethod
    def _ineligible_result(job: Job) -> RecruiterEvaluationResult:
        reasons = job.eligibility_reasons[:8] or ["Deterministic eligibility rejected the job"]
        return RecruiterEvaluationResult(
            recommendation=Recommendation.INELIGIBLE,
            match_score=0,
            confidence_score=100,
            eligibility_confirmed=False,
            role_category=RoleCategory.OTHER,
            seniority_assessment=SeniorityAssessment.UNCLEAR,
            compensation_assessment=(
                CompensationAssessment.UNDISCLOSED
                if job.compensation_currency is None
                else CompensationAssessment.UNCLEAR
            ),
            location_assessment=LocationAssessment.INELIGIBLE,
            matched_skills=[],
            missing_required_skills=[],
            transferable_skills=[],
            strongest_verified_evidence=[],
            concerns=reasons,
            recommended_portfolio_projects=[],
            tailored_positioning=(
                "Do not prepare an application while deterministic constraints fail."
            ),
            evaluation_summary=(
                "The deterministic eligibility rules classify this job as ineligible."
            ),
            should_prepare_application=False,
        )


async def run_configured_evaluations(
    session: AsyncSession,
    settings: Settings,
    options: EvaluationRunOptions,
    *,
    provider: RecruiterEvaluationProvider | None = None,
) -> EvaluationRunSummary:
    candidate_profile = load_candidate_profile(settings)
    preferences = load_job_preferences(settings)
    owned_provider: OpenAIRecruiterEvaluationProvider | None = None
    if provider is None and not options.dry_run:
        api_key = settings.openai_key_value()
        if api_key is None:
            daily_used = await EvaluationRepository(session).count_daily_requests(datetime.now(UTC))
            return EvaluationRunSummary(
                daily_budget_remaining=max(0, settings.openai_max_evaluations_per_day - daily_used),
                errors=[
                    f"{EvaluationErrorCategory.CONFIGURATION_ERROR.value}: "
                    "OPENAI_API_KEY is not configured"
                ],
            )
        model = settings.openai_model_value()
        if model is None:
            daily_used = await EvaluationRepository(session).count_daily_requests(datetime.now(UTC))
            return EvaluationRunSummary(
                daily_budget_remaining=max(0, settings.openai_max_evaluations_per_day - daily_used),
                errors=[
                    f"{EvaluationErrorCategory.CONFIGURATION_ERROR.value}: "
                    "OPENAI_RECRUITER_MODEL is not configured"
                ],
            )
        owned_provider = OpenAIRecruiterEvaluationProvider(
            api_key=api_key,
            model=model,
            timeout_seconds=settings.openai_request_timeout_seconds,
        )
        provider = owned_provider
    try:
        return await EvaluationOrchestrator(
            session,
            settings,
            candidate_profile,
            preferences,
            provider,
        ).run(options)
    finally:
        if owned_provider is not None:
            await owned_provider.close()
