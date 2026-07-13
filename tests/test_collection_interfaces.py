from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.schemas.pipeline import CollectionSummary
from scripts import collect_jobs


@pytest.mark.asyncio
async def test_cli_exit_code_reflects_meaningful_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}",
        _env_file=None,
    )
    monkeypatch.setattr(collect_jobs, "load_settings", lambda: settings)

    async def success(*args: object, **kwargs: object) -> CollectionSummary:
        return CollectionSummary(sources_attempted=2, sources_succeeded=1, sources_failed=1)

    monkeypatch.setattr(collect_jobs, "collect_configured_jobs", success)
    assert await collect_jobs.run("greenhouse") == 0

    async def failure(*args: object, **kwargs: object) -> CollectionSummary:
        return CollectionSummary(sources_attempted=1, sources_failed=1)

    monkeypatch.setattr(collect_jobs, "collect_configured_jobs", failure)
    assert await collect_jobs.run("greenhouse") == 1


def test_api_collection_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'api.db'}",
        _env_file=None,
    )

    async def result(*args: object, **kwargs: object) -> CollectionSummary:
        return CollectionSummary(sources_attempted=1, sources_succeeded=1, jobs_inserted=3)

    monkeypatch.setattr("app.api.routes.collect_configured_jobs", result)
    with TestClient(create_app(settings)) as client:
        response = client.post("/runs/collect", params={"source": "greenhouse"})

    assert response.status_code == 200
    assert response.json()["sources_succeeded"] == 1
    assert response.json()["jobs_inserted"] == 3
