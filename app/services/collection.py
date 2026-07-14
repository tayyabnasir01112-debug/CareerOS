import re
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.ashby import AshbyCollector
from app.collectors.base import JobCollector
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.http import ResilientHttpClient
from app.collectors.lever import LeverCollector
from app.core.config import Settings
from app.core.security import redact_sensitive_text
from app.db.models import (
    CollectorRun,
    Company,
    EligibilityStatus,
    Job,
    RunStatus,
)
from app.schemas.collector import CollectedJob
from app.schemas.configuration import JobPreferences, SourceConfig
from app.schemas.pipeline import CollectionSummary, CollectorPlatform
from app.services.configuration import (
    load_candidate_profile,
    load_job_preferences,
    load_source_config,
)
from app.services.deduplication import FingerprintInput, JobDeduplicationService
from app.services.eligibility import EligibilityDecision, EligibilityJob, EligibilityService
from app.services.evaluation_priority import EvaluationPriorityService

PersistResult = Literal["inserted", "updated", "duplicate"]


def build_collectors(
    config: SourceConfig,
    http: ResilientHttpClient,
    source: CollectorPlatform | None = None,
) -> list[JobCollector]:
    collectors: list[JobCollector] = []
    if source in {None, "greenhouse"} and config.greenhouse.enabled:
        collectors.extend(GreenhouseCollector(board, http) for board in config.greenhouse.boards)
    if source in {None, "lever"} and config.lever.enabled:
        collectors.extend(LeverCollector(site, http) for site in config.lever.sites)
    if source in {None, "ashby"} and config.ashby.enabled:
        collectors.extend(AshbyCollector(board, http) for board in config.ashby.boards)
    return collectors


async def collect_configured_jobs(
    session: AsyncSession,
    settings: Settings,
    *,
    source: CollectorPlatform | None = None,
) -> CollectionSummary:
    source_config = load_source_config(settings)
    preferences = load_job_preferences(settings)
    candidate_profile = load_candidate_profile(settings)
    collection = source_config.collection
    limits = httpx.Limits(
        max_connections=collection.max_concurrency,
        max_keepalive_connections=collection.max_concurrency,
    )
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(collection.request_timeout_seconds),
        headers={"User-Agent": collection.user_agent, "Accept": "application/json"},
        follow_redirects=False,
        limits=limits,
    ) as client:
        http = ResilientHttpClient(
            client,
            max_retries=collection.max_retries,
            backoff_seconds=collection.backoff_seconds,
            max_concurrency=collection.max_concurrency,
            max_response_bytes=collection.max_response_bytes,
        )
        collectors = build_collectors(source_config, http, source)
        return await CollectionPipeline(
            session,
            preferences,
            collectors,
            priority=EvaluationPriorityService(candidate_profile, preferences),
        ).run()


class CollectionPipeline:
    def __init__(
        self,
        session: AsyncSession,
        preferences: JobPreferences,
        collectors: Sequence[JobCollector],
        *,
        priority: EvaluationPriorityService | None = None,
    ) -> None:
        self.session = session
        self.collectors = collectors
        self.eligibility = EligibilityService(preferences)
        self.priority = priority

    async def run(self) -> CollectionSummary:
        summary = CollectionSummary(sources_attempted=len(self.collectors))
        for collector in self.collectors:
            await self._run_collector(collector, summary)
        if not self.collectors:
            summary.errors.append("No enabled collector identifiers matched the request")
        return summary

    async def _run_collector(self, collector: JobCollector, summary: CollectionSummary) -> None:
        run = CollectorRun(collector_name=collector.name, status=RunStatus.RUNNING)
        self.session.add(run)
        await self.session.flush()
        fetched = inserted = updated = duplicates = eligible = flagged = rejected = 0
        try:
            async for collected_job in collector.collect():
                fetched += 1
                outcome, decision = await self._persist_job(collected_job)
                if outcome == "inserted":
                    inserted += 1
                elif outcome == "updated":
                    updated += 1
                else:
                    duplicates += 1
                if decision == EligibilityDecision.ELIGIBLE:
                    eligible += 1
                elif decision == EligibilityDecision.FLAGGED:
                    flagged += 1
                elif decision == EligibilityDecision.REJECTED:
                    rejected += 1
            run.status = RunStatus.SUCCEEDED
            summary.sources_succeeded += 1
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error_message = sanitize_error(exc)
            summary.sources_failed += 1
            summary.errors.append(f"{collector.name}: {run.error_message}")
        run.finished_at = datetime.now(UTC)
        run.jobs_seen = fetched
        run.jobs_created = inserted
        run.jobs_updated = updated
        run.details = {
            "duplicates_skipped": duplicates,
            "jobs_eligible": eligible,
            "jobs_flagged": flagged,
            "jobs_rejected": rejected,
        }
        summary.jobs_fetched += fetched
        summary.jobs_inserted += inserted
        summary.jobs_updated += updated
        summary.duplicates_skipped += duplicates
        summary.jobs_eligible += eligible
        summary.jobs_flagged += flagged
        summary.jobs_rejected += rejected
        await self.session.commit()

    async def _persist_job(
        self, collected: CollectedJob
    ) -> tuple[PersistResult, EligibilityDecision | None]:
        fingerprint = JobDeduplicationService.fingerprint(
            FingerprintInput(
                title=collected.title,
                company=collected.company_name,
                location=collected.location,
            )
        )
        existing = await self.session.scalar(
            select(Job).where(
                Job.source == collected.source,
                Job.external_job_id == collected.external_job_id,
            )
        )
        if existing is not None:
            if existing.fingerprint != fingerprint:
                fingerprint_match = await self.session.scalar(
                    select(Job.id).where(
                        Job.fingerprint == fingerprint,
                        Job.id != existing.id,
                    )
                )
                if fingerprint_match is not None:
                    existing.collected_at = collected.collected_at
                    return "duplicate", None
            changed = self._update_job(existing, collected, fingerprint)
            decision = self._apply_eligibility(existing, collected)
            return ("updated" if changed else "duplicate"), decision if changed else None

        fingerprint_match = await self.session.scalar(
            select(Job.id).where(Job.fingerprint == fingerprint).limit(1)
        )
        if fingerprint_match is not None:
            return "duplicate", None

        company = await self._get_or_create_company(collected.company_name)
        job = Job(
            source=collected.source,
            external_job_id=collected.external_job_id,
            fingerprint=fingerprint,
            title=collected.title,
            normalized_title=JobDeduplicationService.normalize_text(collected.title),
            company=company,
            location=collected.location,
            location_type=collected.location_type,
            employment_type=collected.employment_type,
            description=collected.description,
            source_url=collected.source_url,
            raw_source_data=collected.raw_source_data,
            published_at=collected.published_at,
            source_updated_at=collected.source_updated_at,
            discovered_at=collected.collected_at,
            collected_at=collected.collected_at,
            salary_text=collected.salary_text,
            compensation_currency=collected.compensation_currency,
            compensation_min=collected.compensation_min,
            compensation_max=collected.compensation_max,
            compensation_period=collected.compensation_period,
        )
        decision = self._apply_eligibility(job, collected)
        self.session.add(job)
        return "inserted", decision

    async def _get_or_create_company(self, name: str) -> Company:
        normalized = JobDeduplicationService.normalize_company(name)
        company = await self.session.scalar(
            select(Company).where(Company.normalized_name == normalized)
        )
        if company is None:
            company = Company(name=name, normalized_name=normalized, raw_data={})
            self.session.add(company)
            await self.session.flush()
        return company

    @staticmethod
    def _update_job(job: Job, collected: CollectedJob, fingerprint: str) -> bool:
        fields: dict[str, object] = {
            "fingerprint": fingerprint,
            "title": collected.title,
            "normalized_title": JobDeduplicationService.normalize_text(collected.title),
            "location": collected.location,
            "location_type": collected.location_type,
            "employment_type": collected.employment_type,
            "description": collected.description,
            "source_url": collected.source_url,
            "raw_source_data": collected.raw_source_data,
            "published_at": collected.published_at,
            "source_updated_at": collected.source_updated_at,
            "salary_text": collected.salary_text,
            "compensation_currency": collected.compensation_currency,
            "compensation_min": collected.compensation_min,
            "compensation_max": collected.compensation_max,
            "compensation_period": collected.compensation_period,
        }
        changed = any(getattr(job, field) != value for field, value in fields.items())
        if changed:
            for field, value in fields.items():
                setattr(job, field, value)
        job.collected_at = collected.collected_at
        return changed

    def _apply_eligibility(self, job: Job, collected: CollectedJob) -> EligibilityDecision:
        result = self.eligibility.evaluate(
            EligibilityJob(
                title=collected.title,
                description=collected.description,
                employment_type=collected.employment_type,
                location=collected.location,
                location_type=collected.location_type,
                published_at=collected.published_at or collected.source_updated_at,
                compensation_currency=collected.compensation_currency,
                compensation_min=collected.compensation_min,
                compensation_max=collected.compensation_max,
                compensation_period=collected.compensation_period,
                relocation_supported=bool(
                    re.search(
                        r"\b(?:relocation (?:support|assistance)|visa sponsorship)\b",
                        collected.description,
                        re.IGNORECASE,
                    )
                ),
            ),
            now=collected.collected_at,
        )
        job.eligibility_status = EligibilityStatus(result.decision.value)
        job.eligibility_reasons = result.reasons
        job.location_classification = result.location_classification
        job.location_evidence = result.location_evidence
        if self.priority is not None:
            job.deterministic_pre_score = self.priority.score(job, now=collected.collected_at)
        return result.decision


def sanitize_error(exc: Exception) -> str:
    message = redact_sensitive_text(str(exc))
    message = re.sub(r"\s+", " ", message).strip()
    if not message:
        message = "collector failed without an error message"
    return f"{type(exc).__name__}: {message[:500]}"
