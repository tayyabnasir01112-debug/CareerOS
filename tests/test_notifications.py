import gzip
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.models import JobEvaluation, JobNotification, NotificationStatus
from app.db.session import Database
from app.schemas.evaluation import EvaluationRunOptions
from app.schemas.notification import (
    NotificationDelivery,
    NotificationErrorCategory,
)
from app.services.evaluation_orchestrator import EvaluationOrchestrator
from app.services.evaluation_provider import FakeRecruiterEvaluationProvider
from app.services.notification import (
    DiscordNotificationService,
    DiscordWebhookProvider,
    FakeNotificationProvider,
    JobNotificationFormatter,
    NotificationFailure,
)
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


async def seed_evaluation(database: Database, *, external_id: str = "notify-1") -> int:
    profile, preferences = configuration()
    async with database.session_factory() as session:
        await add_job(session, external_id=external_id)
        await session.commit()
        await EvaluationOrchestrator(
            session,
            settings_for(Path("unused.db")),
            profile,
            preferences,
            FakeRecruiterEvaluationProvider([provider_evaluation()]),
        ).run(EvaluationRunOptions())
        evaluation = await session.scalar(select(JobEvaluation))
        assert evaluation is not None
        return evaluation.id


@pytest.mark.asyncio
async def test_formatter_respects_discord_limits(tmp_path: Path) -> None:
    database = Database(settings_for(tmp_path / "format.db").database_url)
    await database.create_schema()
    try:
        await seed_evaluation(database)
        async with database.session_factory() as session:
            evaluation = await session.scalar(select(JobEvaluation))
            assert evaluation is not None
            await session.refresh(evaluation, ["job"])
            await session.refresh(evaluation.job, ["company"])
            result = provider_evaluation().result.model_copy(
                update={
                    "tailored_positioning": "P" * 800,
                    "matched_skills": ["skill" * 100] * 12,
                    "missing_required_skills": ["missing" * 100] * 10,
                }
            )
            payload = JobNotificationFormatter().format(evaluation.job, result)
            embed = payload.embeds[0]
            fields = embed["fields"]
            assert len(embed["title"]) <= 256
            assert len(fields) <= 25
            assert all(len(field["name"]) <= 256 for field in fields)
            assert all(len(field["value"]) <= 1024 for field in fields)
            combined = len(embed["title"]) + sum(
                len(field["name"]) + len(field["value"]) for field in fields
            )
            assert combined <= 6000
            assert payload.allowed_mentions == {"parse": []}
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_success_persistence_and_duplicate_suppression(tmp_path: Path) -> None:
    database = Database(settings_for(tmp_path / "dedupe.db").database_url)
    await database.create_schema()
    provider = FakeNotificationProvider(
        [NotificationDelivery(provider_response_id="discord-message-1")]
    )
    try:
        await seed_evaluation(database)
        async with database.session_factory() as session:
            service = DiscordNotificationService(session, provider)
            first = await service.run(minimum_score=75, limit=5)
            second = await service.run(minimum_score=75, limit=5)
            notification = await session.scalar(select(JobNotification))

            assert first.notifications_sent == 1
            assert second.notifications_skipped == 1
            assert len(provider.payloads) == 1
            assert notification is not None
            assert notification.status == NotificationStatus.SENT
            assert notification.provider_response_id == "discord-message-1"
            assert await session.scalar(select(func.count()).select_from(JobNotification)) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failed_notification_is_retryable_on_later_run(tmp_path: Path) -> None:
    database = Database(settings_for(tmp_path / "retry.db").database_url)
    await database.create_schema()
    try:
        await seed_evaluation(database)
        async with database.session_factory() as session:
            failed = FakeNotificationProvider(
                [
                    NotificationFailure(
                        NotificationErrorCategory.TRANSIENT_PROVIDER_ERROR,
                        "temporary failure " + "sk-" + "secret-value-1234567890",
                    )
                ]
            )
            first = await DiscordNotificationService(session, failed).run(minimum_score=75, limit=5)
            successful = FakeNotificationProvider([NotificationDelivery()])
            second = await DiscordNotificationService(session, successful).run(
                minimum_score=75, limit=5
            )
            notification = await session.scalar(select(JobNotification))

            assert first.notification_failures == 1
            assert second.notifications_sent == 1
            assert notification is not None
            assert notification.status == NotificationStatus.SENT
            assert notification.attempt_count == 2
            assert "secret-value" not in " ".join(first.errors)
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_rate_limit_retries_then_succeeds() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, request=request)
        return httpx.Response(200, json={"id": "message-2"}, request=request)

    provider = DiscordWebhookProvider(
        "https://discord.com/api/webhooks/123456789/.fixture-token",
        timeout_seconds=1,
        max_retries=1,
        retry_base_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        from app.schemas.notification import DiscordPayload

        result = await provider.send(DiscordPayload(embeds=[{"title": "Test"}]))
        assert result.provider_response_id == "message-2"
        assert result.attempts == 2
        assert calls == 2
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_compressed_success_response_is_decoded_once() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = gzip.compress(b'{"id":"compressed-message"}')
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            content=body,
            request=request,
        )

    provider = DiscordWebhookProvider(
        "https://discord.com/api/webhooks/123456789/.fixture-token",
        timeout_seconds=1,
        max_retries=0,
        retry_base_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        from app.schemas.notification import DiscordPayload

        result = await provider.send(DiscordPayload(embeds=[{"title": "Test"}]))
        assert result.provider_response_id == "compressed-message"
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_deleted_webhook_is_fatal_and_not_retried() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(404, request=request)

    provider = DiscordWebhookProvider(
        "https://discord.com/api/webhooks/123456789/.fixture-token",
        timeout_seconds=1,
        max_retries=2,
        retry_base_seconds=0,
        transport=httpx.MockTransport(handler),
    )
    try:
        from app.schemas.notification import DiscordPayload

        with pytest.raises(NotificationFailure) as captured:
            await provider.send(DiscordPayload(embeds=[{"title": "Test"}]))
        assert captured.value.category == NotificationErrorCategory.INVALID_WEBHOOK_ERROR
        assert captured.value.fatal is True
        assert calls == 1
    finally:
        await provider.close()


def test_webhook_configuration_validation() -> None:
    valid = Settings(
        discord_webhook_url="https://discord.com/api/webhooks/123456789/.fixture-token",
        _env_file=None,
    )
    assert valid.discord_webhook_value() is not None
    with pytest.raises(ValueError, match="standard HTTPS Discord webhook"):
        Settings(discord_webhook_url="https://example.test/webhook", _env_file=None)
