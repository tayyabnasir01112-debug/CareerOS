import asyncio
import hashlib
import json
import random
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Protocol, cast

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import redact_sensitive_text
from app.db.models import (
    EligibilityStatus,
    Job,
    JobEvaluation,
    JobNotification,
    NotificationStatus,
)
from app.schemas.evaluation import Recommendation, RecruiterEvaluationResult
from app.schemas.notification import (
    DiscordPayload,
    NotificationDelivery,
    NotificationErrorCategory,
    NotificationRead,
    NotificationRunSummary,
    PaginatedNotifications,
)
from app.services.evaluation_input import sanitize_prompt_text

_MAX_RESPONSE_BYTES = 65_536
_ALLOWED_RECOMMENDATIONS = {
    Recommendation.STRONG_APPLY,
    Recommendation.APPLY,
    Recommendation.CONSIDER,
}


class NotificationFailure(RuntimeError):
    def __init__(
        self,
        category: NotificationErrorCategory,
        summary: str,
        *,
        retryable: bool = False,
        fatal: bool = False,
    ) -> None:
        super().__init__(redact_sensitive_text(summary)[:500])
        self.category = category
        self.retryable = retryable
        self.fatal = fatal
        self.retry_after: float | None = None
        self.attempts = 1


class NotificationProvider(Protocol):
    async def send(self, payload: DiscordPayload) -> NotificationDelivery: ...


class DiscordWebhookProvider:
    def __init__(
        self,
        webhook_url: str,
        *,
        timeout_seconds: float,
        max_retries: int,
        retry_base_seconds: float,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        random_value: Callable[[], float] = random.random,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.max_retries = max_retries
        self.retry_base_seconds = retry_base_seconds
        self.sleep = sleep
        self.random_value = random_value
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            transport=transport,
            headers={"User-Agent": "CareerOS/0.3 personal-job-research"},
        )

    async def send(self, payload: DiscordPayload) -> NotificationDelivery:
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._request(payload)
                delivery = self._handle_response(response, attempt + 1)
                if delivery is not None:
                    return delivery
            except httpx.TimeoutException:
                failure = NotificationFailure(
                    NotificationErrorCategory.TIMEOUT_ERROR,
                    "Discord request timed out",
                    retryable=True,
                )
            except httpx.TransportError:
                failure = NotificationFailure(
                    NotificationErrorCategory.TRANSIENT_PROVIDER_ERROR,
                    "Discord was temporarily unavailable",
                    retryable=True,
                )
            except NotificationFailure as exc:
                failure = exc

            if not failure.retryable or attempt >= self.max_retries:
                failure.attempts = attempt + 1
                raise failure
            retry_after = failure.retry_after
            delay = (
                retry_after
                if isinstance(retry_after, float)
                else self.retry_base_seconds * (2**attempt) * (1 + 0.25 * self.random_value())
            )
            await self.sleep(min(delay, 30.0))
        raise AssertionError("Discord retry loop terminated unexpectedly")

    async def _request(self, payload: DiscordPayload) -> httpx.Response:
        async with self.client.stream(
            "POST",
            self.webhook_url,
            params={"wait": "true"},
            json=payload.model_dump(mode="json"),
        ) as response:
            content_length = response.headers.get("content-length")
            if content_length is not None:
                try:
                    if int(content_length) > _MAX_RESPONSE_BYTES:
                        raise NotificationFailure(
                            NotificationErrorCategory.INVALID_RESPONSE_ERROR,
                            "Discord response exceeded the configured size limit",
                        )
                except ValueError:
                    pass
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > _MAX_RESPONSE_BYTES:
                    raise NotificationFailure(
                        NotificationErrorCategory.INVALID_RESPONSE_ERROR,
                        "Discord response exceeded the configured size limit",
                    )
            return httpx.Response(
                response.status_code,
                headers={
                    key: value
                    for key, value in response.headers.items()
                    if key.lower()
                    not in {"content-encoding", "content-length", "transfer-encoding"}
                },
                content=bytes(content),
                request=response.request,
            )

    def _handle_response(
        self, response: httpx.Response, attempts: int
    ) -> NotificationDelivery | None:
        if len(response.content) > _MAX_RESPONSE_BYTES:
            raise NotificationFailure(
                NotificationErrorCategory.INVALID_RESPONSE_ERROR,
                "Discord response exceeded the configured size limit",
            )
        if response.status_code in {200, 204}:
            response_id: str | None = None
            if response.content:
                try:
                    body = response.json()
                except ValueError as exc:
                    raise NotificationFailure(
                        NotificationErrorCategory.INVALID_RESPONSE_ERROR,
                        "Discord returned an invalid success response",
                    ) from exc
                if isinstance(body, dict) and body.get("id") is not None:
                    response_id = str(body["id"])
            return NotificationDelivery(provider_response_id=response_id, attempts=attempts)
        if response.status_code == 429:
            failure = NotificationFailure(
                NotificationErrorCategory.RATE_LIMIT_ERROR,
                "Discord rate limit was reached",
                retryable=True,
            )
            retry_header = response.headers.get("retry-after")
            if retry_header:
                try:
                    failure.retry_after = max(0.0, float(retry_header))
                except ValueError:
                    pass
            raise failure
        if response.status_code in {401, 403}:
            raise NotificationFailure(
                NotificationErrorCategory.AUTHENTICATION_ERROR,
                "Discord rejected the webhook credentials",
                fatal=True,
            )
        if response.status_code == 404:
            raise NotificationFailure(
                NotificationErrorCategory.INVALID_WEBHOOK_ERROR,
                "Discord webhook is invalid or has been deleted",
                fatal=True,
            )
        if 500 <= response.status_code < 600:
            raise NotificationFailure(
                NotificationErrorCategory.TRANSIENT_PROVIDER_ERROR,
                f"Discord returned HTTP {response.status_code}",
                retryable=True,
            )
        raise NotificationFailure(
            NotificationErrorCategory.UNKNOWN_PROVIDER_ERROR,
            f"Discord returned HTTP {response.status_code}",
        )

    async def close(self) -> None:
        await self.client.aclose()


class FakeNotificationProvider:
    def __init__(self, outcomes: Sequence[NotificationDelivery | NotificationFailure]) -> None:
        self.outcomes = list(outcomes)
        self.payloads: list[DiscordPayload] = []

    async def send(self, payload: DiscordPayload) -> NotificationDelivery:
        self.payloads.append(payload)
        if not self.outcomes:
            raise NotificationFailure(
                NotificationErrorCategory.UNKNOWN_PROVIDER_ERROR,
                "Fake notification provider has no configured outcome",
            )
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, NotificationFailure):
            raise outcome
        return outcome


class JobNotificationFormatter:
    @staticmethod
    def _clean(value: str, maximum: int) -> str:
        cleaned = sanitize_prompt_text(value).strip() or "Not available"
        return cleaned if len(cleaned) <= maximum else f"{cleaned[: maximum - 1]}…"

    def format(self, job: Job, evaluation: RecruiterEvaluationResult) -> DiscordPayload:
        skills = ", ".join(evaluation.matched_skills[:8]) or "None listed"
        missing = ", ".join(evaluation.missing_required_skills[:5]) or "None identified"
        concern = evaluation.concerns[0] if evaluation.concerns else "No major concern identified"
        posted = job.published_at or job.source_updated_at
        fields = [
            {"name": "Company", "value": self._clean(job.company.name, 300), "inline": True},
            {
                "name": "Location",
                "value": self._clean(job.location or "Undisclosed", 300),
                "inline": True,
            },
            {
                "name": "Source / posted",
                "value": self._clean(
                    f"{job.source} / {posted.date().isoformat() if posted else 'undisclosed'}", 300
                ),
                "inline": True,
            },
            {
                "name": "Recommendation",
                "value": self._clean(
                    f"{evaluation.recommendation.value} - match "
                    f"{evaluation.match_score}/100 - confidence "
                    f"{evaluation.confidence_score}/100",
                    500,
                ),
                "inline": False,
            },
            {
                "name": "Role category",
                "value": self._clean(evaluation.role_category.value, 300),
                "inline": True,
            },
            {"name": "Strongest matches", "value": self._clean(skills, 700), "inline": False},
            {"name": "Missing requirements", "value": self._clean(missing, 700), "inline": False},
            {"name": "Key concern", "value": self._clean(concern, 700), "inline": False},
            {
                "name": "Positioning",
                "value": self._clean(evaluation.tailored_positioning, 900),
                "inline": False,
            },
            {
                "name": "Prepare application",
                "value": "Yes" if evaluation.should_prepare_application else "No",
                "inline": True,
            },
        ]
        embed = {
            "title": self._clean(job.title, 256),
            "url": job.source_url,
            "color": 0x2B90D9,
            "fields": fields,
            "footer": {"text": "CareerOS - verified candidate evidence only"},
        }
        return DiscordPayload(embeds=[embed])


def evaluation_notification_fingerprint(evaluation: JobEvaluation) -> str:
    value = json.dumps(
        {
            "input_hash": evaluation.input_hash,
            "result": evaluation.structured_result,
            "prompt_version": evaluation.prompt_version,
            "model": evaluation.model_name,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(value.encode()).hexdigest()


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def candidates(self, *, minimum_score: int, limit: int) -> list[JobEvaluation]:
        statement = (
            select(JobEvaluation)
            .join(JobEvaluation.job)
            .options(selectinload(JobEvaluation.job).selectinload(Job.company))
            .where(
                JobEvaluation.status == "success",
                JobEvaluation.match_score >= minimum_score,
                JobEvaluation.recommendation.in_([item.value for item in _ALLOWED_RECOMMENDATIONS]),
                Job.eligibility_status.in_([EligibilityStatus.ELIGIBLE, EligibilityStatus.FLAGGED]),
            )
            .order_by(JobEvaluation.created_at.desc(), JobEvaluation.id.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def get_by_fingerprint(self, fingerprint: str) -> JobNotification | None:
        return cast(
            JobNotification | None,
            await self.session.scalar(
                select(JobNotification).where(
                    JobNotification.channel_type == "discord",
                    JobNotification.evaluation_fingerprint == fingerprint,
                )
            ),
        )

    async def save_success(
        self,
        evaluation: JobEvaluation,
        fingerprint: str,
        delivery: NotificationDelivery,
        existing: JobNotification | None,
    ) -> JobNotification:
        notification = existing or JobNotification(
            job_id=evaluation.job_id,
            evaluation_id=evaluation.id,
            channel_type="discord",
            evaluation_fingerprint=fingerprint,
        )
        notification.status = NotificationStatus.SENT
        notification.provider_response_id = delivery.provider_response_id
        notification.attempt_count = (notification.attempt_count or 0) + delivery.attempts
        notification.error_category = None
        notification.error_summary = None
        notification.sent_at = datetime.now(UTC)
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def save_failure(
        self,
        evaluation: JobEvaluation,
        fingerprint: str,
        failure: NotificationFailure,
        existing: JobNotification | None,
    ) -> JobNotification:
        notification = existing or JobNotification(
            job_id=evaluation.job_id,
            evaluation_id=evaluation.id,
            channel_type="discord",
            evaluation_fingerprint=fingerprint,
        )
        notification.status = NotificationStatus.FAILED
        notification.attempt_count = (notification.attempt_count or 0) + failure.attempts
        notification.error_category = failure.category.value
        notification.error_summary = str(failure)[:500]
        self.session.add(notification)
        await self.session.flush()
        return notification

    async def list(self, *, limit: int, offset: int) -> PaginatedNotifications:
        items = list(
            (
                await self.session.scalars(
                    select(JobNotification)
                    .order_by(JobNotification.created_at.desc(), JobNotification.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            ).all()
        )
        total = int(
            await self.session.scalar(select(func.count()).select_from(JobNotification)) or 0
        )
        return PaginatedNotifications(
            items=[NotificationRead.model_validate(item) for item in items],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def get(self, notification_id: int) -> JobNotification | None:
        return cast(
            JobNotification | None, await self.session.get(JobNotification, notification_id)
        )


class DiscordNotificationService:
    def __init__(self, session: AsyncSession, provider: NotificationProvider) -> None:
        self.session = session
        self.provider = provider
        self.repository = NotificationRepository(session)
        self.formatter = JobNotificationFormatter()

    async def run(
        self, *, minimum_score: int, limit: int, dry_run: bool = False
    ) -> NotificationRunSummary:
        summary = NotificationRunSummary()
        evaluations = await self.repository.candidates(
            minimum_score=minimum_score,
            limit=max(limit * 20, limit),
        )
        delivery_attempts = 0
        for index, evaluation in enumerate(evaluations):
            fingerprint = evaluation_notification_fingerprint(evaluation)
            existing = await self.repository.get_by_fingerprint(fingerprint)
            if existing is not None and existing.status == NotificationStatus.SENT:
                summary.notifications_skipped += 1
                continue
            if dry_run:
                summary.notifications_skipped += 1
                continue
            if delivery_attempts >= limit:
                summary.notifications_skipped += len(evaluations) - index
                break
            delivery_attempts += 1
            result = RecruiterEvaluationResult.model_validate(evaluation.structured_result)
            try:
                delivery = await self.provider.send(self.formatter.format(evaluation.job, result))
            except NotificationFailure as exc:
                await self.repository.save_failure(evaluation, fingerprint, exc, existing)
                await self.session.commit()
                summary.notification_failures += 1
                summary.errors.append(f"job {evaluation.job_id}: {exc.category.value}: {exc}")
                if exc.fatal:
                    break
                continue
            await self.repository.save_success(evaluation, fingerprint, delivery, existing)
            await self.session.commit()
            summary.notifications_sent += 1
        return summary
