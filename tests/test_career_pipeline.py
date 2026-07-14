import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import Database
from app.main import create_app
from app.schemas.evaluation import EvaluationRunOptions
from app.schemas.notification import (
    CareerPipelineSummary,
    NotificationDelivery,
    PipelineRunOptions,
)
from app.schemas.pipeline import CollectionSummary
from app.services.career_pipeline import CareerPipelineOrchestrator
from app.services.evaluation_orchestrator import EvaluationOrchestrator
from app.services.evaluation_provider import FakeRecruiterEvaluationProvider
from app.services.notification import (
    DiscordNotificationService,
    FakeNotificationProvider,
)
from scripts import run_career_pipeline as pipeline_cli
from tests.evaluation_helpers import add_job, provider_evaluation
from tests.test_evaluation_orchestrator import configuration


def settings_for(path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "database_url": f"sqlite+aiosqlite:///{path}",
        "openai_recruiter_model": "fixture-model",
        "discord_webhook_url": "https://discord.com/api/webhooks/123456789/.fixture-token",
        "discord_retry_base_seconds": 0,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings.model_validate(values)


async def collection_result(*args: object, **kwargs: object) -> CollectionSummary:
    return CollectionSummary(
        sources_attempted=2,
        sources_succeeded=1,
        sources_failed=1,
        jobs_fetched=1,
        jobs_inserted=1,
        jobs_flagged=1,
        errors=["lever: sanitized partial failure"],
    )


@pytest.mark.asyncio
async def test_full_pipeline_with_fakes_and_partial_source_failure(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "pipeline.db")
    database = Database(settings.database_url)
    await database.create_schema()
    notification_provider = FakeNotificationProvider(
        [NotificationDelivery(provider_response_id="discord-1")]
    )
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="pipeline-1")
            await session.commit()
            summary = await CareerPipelineOrchestrator(
                session,
                settings,
                evaluation_provider=FakeRecruiterEvaluationProvider([provider_evaluation()]),
                notification_provider=notification_provider,
                collection_runner=collection_result,
            ).run(PipelineRunOptions(limit=1))

            assert summary.jobs_fetched == 1
            assert summary.jobs_evaluated == 1
            assert summary.notifications_sent == 1
            assert summary.total_input_tokens == 120
            assert "sanitized partial failure" in summary.errors[0]
            assert len(notification_provider.payloads) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_cached_evaluation_can_be_notified(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "cached.db")
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="cached-pipeline")
            await session.commit()
            await EvaluationOrchestrator(
                session,
                settings,
                profile,
                preferences,
                FakeRecruiterEvaluationProvider([provider_evaluation()]),
            ).run(EvaluationRunOptions())
            provider = FakeNotificationProvider([NotificationDelivery()])
            summary = await CareerPipelineOrchestrator(
                session,
                settings,
                evaluation_provider=FakeRecruiterEvaluationProvider([]),
                notification_provider=provider,
                collection_runner=collection_result,
            ).run(PipelineRunOptions(limit=1))

            assert summary.cached_evaluations_reused == 1
            assert summary.notifications_sent == 1
            assert len(provider.payloads) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "options",
    [PipelineRunOptions(dry_run=True), PipelineRunOptions(no_notify=True)],
)
async def test_dry_run_and_no_notify_never_send(
    tmp_path: Path, options: PipelineRunOptions
) -> None:
    settings = settings_for(tmp_path / f"skip-{options.dry_run}.db")
    database = Database(settings.database_url)
    await database.create_schema()
    provider = FakeNotificationProvider([])
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id=f"skip-{options.dry_run}")
            await session.commit()
            summary = await CareerPipelineOrchestrator(
                session,
                settings,
                evaluation_provider=FakeRecruiterEvaluationProvider([provider_evaluation()]),
                notification_provider=provider,
                collection_runner=collection_result,
            ).run(options)
            assert summary.notifications_sent == 0
            assert provider.payloads == []
            if options.dry_run:
                assert summary.jobs_evaluated == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_disabled_or_missing_webhook_skips_notifications(tmp_path: Path) -> None:
    for suffix, overrides in (
        ("disabled", {"discord_notifications_enabled": False}),
        ("missing", {"discord_webhook_url": None}),
    ):
        settings = settings_for(tmp_path / f"{suffix}.db", **overrides)
        database = Database(settings.database_url)
        await database.create_schema()
        profile, preferences = configuration()
        try:
            async with database.session_factory() as session:
                await add_job(session, external_id=suffix)
                await session.commit()
                await EvaluationOrchestrator(
                    session,
                    settings,
                    profile,
                    preferences,
                    FakeRecruiterEvaluationProvider([provider_evaluation()]),
                ).run(EvaluationRunOptions())
                summary = await CareerPipelineOrchestrator(
                    session,
                    settings,
                    evaluation_provider=FakeRecruiterEvaluationProvider([]),
                    collection_runner=collection_result,
                ).run(PipelineRunOptions(no_notify=False))
                assert summary.notifications_sent == 0
                assert summary.notifications_skipped == 1
        finally:
            await database.dispose()


@pytest.mark.asyncio
async def test_notification_limit_per_run(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "limit.db", discord_max_notifications_per_run=1)
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="limit-1")
            await add_job(session, external_id="limit-2")
            await session.commit()
            await EvaluationOrchestrator(
                session,
                settings,
                profile,
                preferences,
                FakeRecruiterEvaluationProvider([provider_evaluation(), provider_evaluation()]),
            ).run(EvaluationRunOptions(limit=2))
            provider = FakeNotificationProvider([NotificationDelivery()])
            result = await DiscordNotificationService(session, provider).run(
                minimum_score=75, limit=1
            )
            assert result.notifications_sent == 1
            assert len(provider.payloads) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_pipeline_cli_behavior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_for(tmp_path / "cli.db")
    monkeypatch.setattr(pipeline_cli, "load_settings", lambda: settings)

    async def fake_run(*args: object, **kwargs: object) -> CareerPipelineSummary:
        return CareerPipelineSummary(jobs_fetched=2, notifications_skipped=1)

    monkeypatch.setattr(pipeline_cli, "run_career_pipeline", fake_run)
    code, summary = await pipeline_cli.run(PipelineRunOptions(dry_run=True))
    assert code == 0
    assert summary.jobs_fetched == 2


def test_pipeline_api_and_notification_pagination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = settings_for(tmp_path / "api.db")

    async def seed() -> int:
        database = Database(settings.database_url)
        await database.create_schema()
        profile, preferences = configuration()
        try:
            async with database.session_factory() as session:
                await add_job(session, external_id="api-notification")
                await session.commit()
                await EvaluationOrchestrator(
                    session,
                    settings,
                    profile,
                    preferences,
                    FakeRecruiterEvaluationProvider([provider_evaluation()]),
                ).run(EvaluationRunOptions())
                await DiscordNotificationService(
                    session, FakeNotificationProvider([NotificationDelivery()])
                ).run(minimum_score=75, limit=1)
                from sqlalchemy import select

                from app.db.models import JobNotification

                notification = await session.scalar(select(JobNotification))
                assert notification is not None
                return notification.id
        finally:
            await database.dispose()

    notification_id = asyncio.run(seed())

    async def fake_pipeline(*args: object, **kwargs: object) -> CareerPipelineSummary:
        return CareerPipelineSummary(jobs_fetched=1, notifications_sent=1)

    monkeypatch.setattr("app.api.routes.run_career_pipeline", fake_pipeline)
    with TestClient(create_app(settings)) as client:
        run_response = client.post("/pipeline/run", json={"dry_run": True, "limit": 1})
        list_response = client.get("/notifications", params={"limit": 1, "offset": 0})
        detail_response = client.get(f"/notifications/{notification_id}")
        invalid_response = client.post(
            "/pipeline/run", json={"webhook_url": "https://example.test", "limit": 1}
        )

    assert run_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1
    assert detail_response.status_code == 200
    assert invalid_response.status_code == 422


def test_windows_task_scripts_are_local_and_secret_free() -> None:
    register = Path("scripts/register_windows_task.ps1").read_text(encoding="utf-8")
    unregister = Path("scripts/unregister_windows_task.ps1").read_text(encoding="utf-8")
    assert ".venv\\Scripts\\python.exe" in register
    assert "IntervalHours = 3" in register
    assert "-WindowStyle Hidden" in register
    assert "-StartWhenAvailable" in register
    assert "-WakeToRun" in register
    assert "-MultipleInstances IgnoreNew" in register
    assert "DISCORD_WEBHOOK_URL" not in register
    assert "OPENAI_API_KEY" not in register
    assert "Unregister-ScheduledTask" in unregister
