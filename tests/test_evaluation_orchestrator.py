from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.models import EligibilityStatus, JobEvaluation
from app.db.session import Database
from app.schemas.configuration import CandidateProfile, JobPreferences
from app.schemas.evaluation import (
    EvaluationErrorCategory,
    EvaluationRunOptions,
    EvaluationStatus,
)
from app.services.configuration import load_yaml_model
from app.services.evaluation_orchestrator import EvaluationOrchestrator, run_configured_evaluations
from app.services.evaluation_provider import (
    FakeRecruiterEvaluationProvider,
    ProviderFailure,
)
from tests.evaluation_helpers import add_job, provider_evaluation


def settings_for(path: Path, **overrides: object) -> Settings:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{path}",
        openai_recruiter_model="fixture-model",
        openai_retry_base_seconds=0,
        openai_max_input_characters=18_000,
        _env_file=None,
    )
    return settings.model_copy(update=overrides)


def configuration() -> tuple[CandidateProfile, JobPreferences]:
    return (
        load_yaml_model(Path("config/candidate_profile.yaml"), CandidateProfile),
        load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences),
    )


@pytest.mark.asyncio
async def test_deterministic_ineligibility_avoids_provider_call(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "ineligible.db")
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    provider = FakeRecruiterEvaluationProvider([])
    try:
        async with database.session_factory() as session:
            await add_job(
                session,
                external_id="ineligible-1",
                eligibility_status=EligibilityStatus.REJECTED,
                eligibility_reasons=["job is unpaid"],
            )
            await session.commit()
            summary = await EvaluationOrchestrator(
                session, settings, profile, preferences, provider
            ).run(EvaluationRunOptions())
            evaluation = await session.scalar(select(JobEvaluation))

            assert summary.skipped_by_deterministic_eligibility == 1
            assert summary.evaluations_requested == 0
            assert provider.calls == []
            assert evaluation is not None
            assert evaluation.status == EvaluationStatus.INELIGIBLE.value
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_success_persistence_cache_reuse_and_force(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "cache.db")
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    first_provider = FakeRecruiterEvaluationProvider([provider_evaluation()])
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="cache-1")
            await session.commit()
            first = await EvaluationOrchestrator(
                session, settings, profile, preferences, first_provider
            ).run(EvaluationRunOptions())
            cached_provider = FakeRecruiterEvaluationProvider([])
            cached = await EvaluationOrchestrator(
                session, settings, profile, preferences, cached_provider
            ).run(EvaluationRunOptions())
            forced_provider = FakeRecruiterEvaluationProvider([provider_evaluation(match_score=91)])
            forced = await EvaluationOrchestrator(
                session, settings, profile, preferences, forced_provider
            ).run(EvaluationRunOptions(force=True))
            evaluations = list((await session.scalars(select(JobEvaluation))).all())

            assert first.evaluations_completed == 1
            assert first.total_input_tokens == 120
            assert first.total_output_tokens == 80
            assert cached.cached_evaluations_reused == 1
            assert cached_provider.calls == []
            assert forced.evaluations_completed == 1
            assert len(evaluations) == 2
            assert evaluations[0].api_response_id == "resp_fixture_123"
            assert evaluations[0].total_tokens == 200
            assert evaluations[0].structured_result is not None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_selection_prioritizes_unevaluated_eligible_backlog(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "selection-priority.db")
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    try:
        async with database.session_factory() as session:
            cached_job = await add_job(session, external_id="already-evaluated")
            await session.commit()
            await EvaluationOrchestrator(
                session,
                settings,
                profile,
                preferences,
                FakeRecruiterEvaluationProvider([provider_evaluation()]),
            ).run(EvaluationRunOptions(job_id=cached_job.id))

            await add_job(
                session,
                external_id="newest-rejected",
                eligibility_status=EligibilityStatus.REJECTED,
            )
            backlog_job = await add_job(session, external_id="eligible-backlog")
            await session.commit()

            provider = FakeRecruiterEvaluationProvider([provider_evaluation()])
            summary = await EvaluationOrchestrator(
                session, settings, profile, preferences, provider
            ).run(EvaluationRunOptions(limit=1))

            assert summary.evaluations_completed == 1
            assert len(provider.calls) == 1
            assert provider.calls[0].job_id == backlog_job.id
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_failed_evaluation_is_retried_on_later_run(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "retry-failed.db", openai_max_retries=0)
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    failure = ProviderFailure(
        EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
        "malformed structured output",
    )
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="retry-1")
            await session.commit()
            failed = await EvaluationOrchestrator(
                session,
                settings,
                profile,
                preferences,
                FakeRecruiterEvaluationProvider([failure]),
            ).run(EvaluationRunOptions())
            retried = await EvaluationOrchestrator(
                session,
                settings,
                profile,
                preferences,
                FakeRecruiterEvaluationProvider([provider_evaluation()]),
            ).run(EvaluationRunOptions())
            statuses = list(await session.scalars(select(JobEvaluation.status)))

            assert failed.failed_evaluations == 1
            assert retried.evaluations_completed == 1
            assert statuses == [EvaluationStatus.FAILED.value, EvaluationStatus.SUCCESS.value]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_per_run_and_utc_daily_budgets(tmp_path: Path) -> None:
    settings = settings_for(
        tmp_path / "budget.db",
        openai_max_evaluations_per_run=1,
        openai_max_evaluations_per_day=1,
    )
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    provider = FakeRecruiterEvaluationProvider([provider_evaluation(), provider_evaluation()])
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="budget-1")
            await add_job(session, external_id="budget-2")
            await session.commit()
            first = await EvaluationOrchestrator(
                session, settings, profile, preferences, provider
            ).run(EvaluationRunOptions(limit=2))
            second = await EvaluationOrchestrator(
                session, settings, profile, preferences, provider
            ).run(EvaluationRunOptions(limit=2, force=True))

            assert first.evaluations_requested == 1
            assert first.daily_budget_remaining == 0
            assert second.evaluations_requested == 0
            assert len(provider.calls) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_dry_run_has_no_provider_calls_or_writes(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "dry.db")
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    provider = FakeRecruiterEvaluationProvider([])
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="dry-1")
            await session.commit()
            summary = await EvaluationOrchestrator(
                session, settings, profile, preferences, provider
            ).run(EvaluationRunOptions(dry_run=True))

            assert summary.jobs_considered == 1
            assert len(summary.dry_run_inputs) == 1
            assert provider.calls == []
            assert await session.scalar(select(func.count()).select_from(JobEvaluation)) == 0
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_live_openai_run_requires_configured_model(tmp_path: Path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'missing-model.db'}",
        openai_api_key="test-key-not-a-real-credential",
        openai_recruiter_model=None,
        openai_retry_base_seconds=0,
        openai_max_input_characters=18_000,
        _env_file=None,
    )
    database = Database(settings.database_url)
    await database.create_schema()
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="missing-model")
            await session.commit()
            summary = await run_configured_evaluations(session, settings, EvaluationRunOptions())

            assert summary.evaluations_requested == 0
            assert summary.errors == [
                f"{EvaluationErrorCategory.CONFIGURATION_ERROR.value}: "
                "OPENAI_RECRUITER_MODEL is not configured"
            ]
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_partial_failure_continues_but_authentication_failure_stops(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "failures.db", openai_max_retries=0)
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="partial-1")
            await add_job(session, external_id="partial-2")
            await session.commit()
            partial_provider = FakeRecruiterEvaluationProvider(
                [
                    ProviderFailure(
                        EvaluationErrorCategory.INVALID_STRUCTURED_OUTPUT,
                        "invalid output",
                    ),
                    provider_evaluation(),
                ]
            )
            partial = await EvaluationOrchestrator(
                session, settings, profile, preferences, partial_provider
            ).run(EvaluationRunOptions(limit=2))

            await add_job(session, external_id="auth-1")
            await add_job(session, external_id="auth-2")
            await session.commit()
            auth_provider = FakeRecruiterEvaluationProvider(
                [
                    ProviderFailure(
                        EvaluationErrorCategory.AUTHENTICATION_ERROR,
                        "authentication failed",
                        fatal=True,
                    ),
                    provider_evaluation(),
                ]
            )
            auth = await EvaluationOrchestrator(
                session, settings, profile, preferences, auth_provider
            ).run(EvaluationRunOptions(limit=2, force=True))

            assert partial.failed_evaluations == 1
            assert partial.evaluations_completed == 1
            assert len(partial_provider.calls) == 2
            assert auth.failed_evaluations == 1
            assert len(auth_provider.calls) == 1
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_timeout_is_retried_and_invalid_output_is_classified(tmp_path: Path) -> None:
    settings = settings_for(tmp_path / "provider-errors.db", openai_max_retries=1)
    database = Database(settings.database_url)
    await database.create_schema()
    profile, preferences = configuration()
    timeout = ProviderFailure(
        EvaluationErrorCategory.TIMEOUT_ERROR,
        "request timed out",
        retryable=True,
    )
    try:
        async with database.session_factory() as session:
            await add_job(session, external_id="timeout-1")
            await session.commit()
            provider = FakeRecruiterEvaluationProvider([timeout, provider_evaluation()])
            summary = await EvaluationOrchestrator(
                session, settings, profile, preferences, provider
            ).run(EvaluationRunOptions())

            assert summary.evaluations_completed == 1
            assert len(provider.calls) == 2
    finally:
        await database.dispose()
