import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.db.session import Database
from app.main import create_app
from app.schemas.evaluation import EvaluationRunOptions, EvaluationRunSummary
from app.services.evaluation_orchestrator import EvaluationOrchestrator
from app.services.evaluation_provider import FakeRecruiterEvaluationProvider
from scripts import evaluate_jobs
from tests.evaluation_helpers import add_job, provider_evaluation
from tests.test_evaluation_orchestrator import configuration


@pytest.mark.asyncio
async def test_evaluation_cli_dry_run_behavior(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cli-evaluation.db'}",
        _env_file=None,
    )
    monkeypatch.setattr(evaluate_jobs, "load_settings", lambda: settings)

    async def dry_result(*args: object, **kwargs: object) -> EvaluationRunSummary:
        return EvaluationRunSummary(jobs_considered=2, daily_budget_remaining=25)

    monkeypatch.setattr(evaluate_jobs, "run_configured_evaluations", dry_result)
    exit_code, summary = await evaluate_jobs.run(EvaluationRunOptions(dry_run=True))

    assert exit_code == 0
    assert summary.jobs_considered == 2


def test_evaluation_api_run_and_paginated_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "evaluation-api.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{database_path}",
        openai_recruiter_model="fixture-model",
        _env_file=None,
    )

    async def seed() -> tuple[int, int]:
        database = Database(settings.database_url)
        await database.create_schema()
        profile, preferences = configuration()
        try:
            async with database.session_factory() as session:
                job = await add_job(session, external_id="api-evaluation-1")
                await session.commit()
                await EvaluationOrchestrator(
                    session,
                    settings,
                    profile,
                    preferences,
                    FakeRecruiterEvaluationProvider(
                        [provider_evaluation(), provider_evaluation(match_score=92)]
                    ),
                ).run(EvaluationRunOptions(force=True))
                await EvaluationOrchestrator(
                    session,
                    settings,
                    profile,
                    preferences,
                    FakeRecruiterEvaluationProvider([provider_evaluation(match_score=92)]),
                ).run(EvaluationRunOptions(force=True))
                from sqlalchemy import select

                from app.db.models import JobEvaluation

                evaluations = list((await session.scalars(select(JobEvaluation))).all())
                return job.id, evaluations[-1].id
        finally:
            await database.dispose()

    job_id, evaluation_id = asyncio.run(seed())

    async def run_result(*args: object, **kwargs: object) -> EvaluationRunSummary:
        return EvaluationRunSummary(
            jobs_considered=1,
            evaluations_completed=1,
            daily_budget_remaining=24,
        )

    monkeypatch.setattr("app.api.routes.run_configured_evaluations", run_result)
    with TestClient(create_app(settings)) as client:
        run_response = client.post(
            "/evaluations/run", json={"job_id": job_id, "limit": 1, "dry_run": True}
        )
        list_response = client.get("/evaluations", params={"limit": 1, "offset": 0})
        detail_response = client.get(f"/evaluations/{evaluation_id}")
        job_response = client.get(f"/jobs/{job_id}/evaluation")
        invalid_response = client.post(
            "/evaluations/run", json={"limit": 0, "model": "caller-controlled"}
        )

    assert run_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 2
    assert len(list_response.json()["items"]) == 1
    assert detail_response.status_code == 200
    assert detail_response.json()["id"] == evaluation_id
    assert job_response.status_code == 200
    assert job_response.json()["id"] == evaluation_id
    assert invalid_response.status_code == 422
