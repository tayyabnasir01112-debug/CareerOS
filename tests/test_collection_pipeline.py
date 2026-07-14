from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.collectors.base import JobCollector
from app.db.models import (
    CollectorRun,
    EligibilityStatus,
    EmploymentType,
    Job,
    LocationType,
    RunStatus,
)
from app.db.session import Database
from app.schemas.collector import CollectedJob
from app.schemas.configuration import JobPreferences
from app.services.collection import CollectionPipeline
from app.services.configuration import load_yaml_model


class FixtureCollector(JobCollector):
    def __init__(
        self, name: str, jobs: list[CollectedJob], *, failure: Exception | None = None
    ) -> None:
        self._name = name
        self.jobs = jobs
        self.failure = failure

    @property
    def name(self) -> str:
        return self._name

    async def collect(self) -> AsyncIterator[CollectedJob]:
        for job in self.jobs:
            yield job
        if self.failure is not None:
            raise self.failure


def job_fixture(
    *,
    source: str = "greenhouse",
    external_id: str = "job-1",
    title: str = "Python Backend Engineer",
    company: str = "Example Company",
    description: str = "Build reliable APIs.",
    collected_at: datetime | None = None,
) -> CollectedJob:
    timestamp = collected_at or datetime(2026, 7, 13, 12, tzinfo=UTC)
    return CollectedJob(
        source=source,
        external_job_id=external_id,
        title=title,
        company_name=company,
        location="Worldwide Remote",
        location_type=LocationType.REMOTE,
        employment_type=EmploymentType.FULL_TIME,
        description=description,
        source_url=f"https://jobs.example.test/{external_id}",
        raw_source_data={"id": external_id, "description": description},
        published_at=timestamp,
        source_updated_at=timestamp,
        collected_at=timestamp,
        salary_text="USD 2,000 monthly",
        compensation_currency="USD",
        compensation_min=2000,
        compensation_max=2500,
        compensation_period="month",
    )


@pytest.fixture
def preferences() -> JobPreferences:
    return load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences)


@pytest.mark.asyncio
async def test_pipeline_insert_update_source_and_cross_source_duplicates(
    tmp_path: Path, preferences: JobPreferences
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'pipeline.db'}")
    await database.create_schema()
    try:
        async with database.session_factory() as session:
            first = await CollectionPipeline(
                session, preferences, [FixtureCollector("greenhouse:example", [job_fixture()])]
            ).run()
            unchanged = await CollectionPipeline(
                session, preferences, [FixtureCollector("greenhouse:example", [job_fixture()])]
            ).run()
            changed_job = job_fixture(description="Build reliable APIs and automation.")
            changed = await CollectionPipeline(
                session, preferences, [FixtureCollector("greenhouse:example", [changed_job])]
            ).run()
            cross_source = await CollectionPipeline(
                session,
                preferences,
                [
                    FixtureCollector(
                        "lever:example", [job_fixture(source="lever", external_id="other")]
                    )
                ],
            ).run()

            assert first.jobs_inserted == 1
            assert first.jobs_eligible == 1
            assert unchanged.duplicates_skipped == 1
            assert changed.jobs_updated == 1
            assert cross_source.duplicates_skipped == 1
            assert await session.scalar(select(func.count()).select_from(Job)) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_pipeline_partial_failure_run_stats_and_eligibility(
    tmp_path: Path, preferences: JobPreferences
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'partial.db'}")
    await database.create_schema()
    eligible = job_fixture()
    rejected = job_fixture(
        external_id="job-2", title="Volunteer Python Role", description="This is unpaid."
    )
    try:
        async with database.session_factory() as session:
            summary = await CollectionPipeline(
                session,
                preferences,
                [
                    FixtureCollector("greenhouse:example", [eligible, rejected]),
                    FixtureCollector("lever:broken", [], failure=RuntimeError("sanitized failure")),
                ],
            ).run()
            runs = list(
                (await session.scalars(select(CollectorRun).order_by(CollectorRun.id))).all()
            )
            jobs = list((await session.scalars(select(Job).order_by(Job.external_job_id))).all())

            assert summary.sources_attempted == 2
            assert summary.sources_succeeded == 1
            assert summary.sources_failed == 1
            assert summary.jobs_fetched == 2
            assert summary.jobs_inserted == 2
            assert summary.jobs_eligible == 1
            assert summary.jobs_rejected == 1
            assert runs[0].jobs_seen == 2
            assert runs[0].jobs_created == 2
            assert runs[0].status == RunStatus.SUCCEEDED
            assert runs[1].status == RunStatus.FAILED
            assert jobs[0].eligibility_status == EligibilityStatus.ELIGIBLE
            assert jobs[1].eligibility_status == EligibilityStatus.REJECTED
    finally:
        await database.dispose()
