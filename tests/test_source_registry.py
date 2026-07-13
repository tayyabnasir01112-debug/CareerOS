from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.schemas.configuration import (
    CollectionSettings,
    RegistryPlatform,
    RegistryValidationStatus,
    RemoteRelevance,
    SourceRegistry,
    SourceRegistryEntry,
)
from app.services.configuration import load_yaml_model
from app.services.source_registry import (
    SourceRegistryValidator,
    build_source_config,
    endpoint_for,
    write_yaml_model,
)


def entry(
    identifier: str,
    platform: RegistryPlatform,
    *,
    enabled: bool = True,
    status: RegistryValidationStatus = RegistryValidationStatus.PENDING,
) -> SourceRegistryEntry:
    host = {
        RegistryPlatform.GREENHOUSE: "job-boards.greenhouse.io",
        RegistryPlatform.LEVER: "jobs.lever.co",
        RegistryPlatform.ASHBY: "jobs.ashbyhq.com",
    }[platform]
    return SourceRegistryEntry(
        company_name=identifier.title(),
        platform=platform,
        identifier=identifier,
        careers_url=f"https://{host}/{identifier}",
        enabled=enabled,
        categories=["python_backend"],
        remote_relevance=RemoteRelevance.HIGH,
        validation_status=status,
    )


@pytest.mark.asyncio
async def test_valid_active_and_empty_sources_are_detected() -> None:
    registry = SourceRegistry(
        schema_version=1,
        sources=[
            entry("green", RegistryPlatform.GREENHOUSE),
            entry("lever", RegistryPlatform.LEVER),
            entry("ashby", RegistryPlatform.ASHBY),
        ],
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if "greenhouse" in request.url.host:
            return httpx.Response(200, json={"jobs": [{"id": 1}]}, request=request)
        if "lever.co" in request.url.host:
            return httpx.Response(200, json=[], request=request)
        return httpx.Response(200, json={"jobs": [{"id": "a"}]}, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        summary = await SourceRegistryValidator(
            client, now=datetime(2026, 7, 13, tzinfo=UTC)
        ).validate(registry, refresh=True)

    assert summary.valid_boards == 3
    assert summary.boards_with_active_jobs == 2
    assert summary.boards_without_current_jobs == 1
    assert registry.sources[1].has_active_jobs is False


@pytest.mark.asyncio
async def test_redirect_auth_and_invalid_shape_are_rejected() -> None:
    registry = SourceRegistry(
        schema_version=1,
        sources=[
            entry("redirected", RegistryPlatform.GREENHOUSE),
            entry("private", RegistryPlatform.LEVER),
            entry("malformed", RegistryPlatform.ASHBY),
        ],
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if "redirected" in str(request.url):
            return httpx.Response(
                302, headers={"location": "https://example.test"}, request=request
            )
        if "private" in str(request.url):
            return httpx.Response(403, request=request)
        return httpx.Response(200, json={"unexpected": []}, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=False
    ) as client:
        summary = await SourceRegistryValidator(client).validate(registry, refresh=True)

    assert summary.invalid_boards == 3
    assert summary.failures_by_platform == {"greenhouse": 1, "lever": 1, "ashby": 1}
    assert all(not source.enabled for source in registry.sources)
    assert all(source.cooldown_until is not None for source in registry.sources)


@pytest.mark.asyncio
async def test_partial_validation_failure_does_not_stop_other_sources() -> None:
    registry = SourceRegistry(
        schema_version=1,
        sources=[
            entry("working", RegistryPlatform.GREENHOUSE),
            entry("broken", RegistryPlatform.GREENHOUSE),
        ],
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        status = 200 if "working" in str(request.url) else 500
        return httpx.Response(status, json={"jobs": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        summary = await SourceRegistryValidator(client).validate(registry, refresh=True)

    assert summary.valid_boards == 1
    assert summary.invalid_boards == 1
    assert registry.sources[0].validation_status == RegistryValidationStatus.VALID


def test_duplicate_identifiers_are_rejected() -> None:
    duplicate = entry("same", RegistryPlatform.LEVER)
    with pytest.raises(ValidationError, match="duplicate source identifier"):
        SourceRegistry(schema_version=1, sources=[duplicate, duplicate.model_copy()])


@pytest.mark.parametrize(
    "identifier",
    ["../escape", "https://example.test", "name/path", "name?token=value", " name "],
)
def test_unsafe_identifiers_are_rejected(identifier: str) -> None:
    with pytest.raises(ValidationError):
        entry(identifier, RegistryPlatform.GREENHOUSE)


def test_credentialed_or_query_careers_urls_are_rejected() -> None:
    values = entry("safe", RegistryPlatform.GREENHOUSE).model_dump()
    values["careers_url"] = "https://user:password@example.test/jobs?token=secret"
    with pytest.raises(ValidationError, match="credentials, query parameters, or fragments"):
        SourceRegistryEntry.model_validate(values)


def test_unrelated_careers_url_host_is_rejected() -> None:
    values = entry("safe", RegistryPlatform.GREENHOUSE).model_dump()
    values["careers_url"] = "https://example.test/safe"
    with pytest.raises(ValidationError, match="canonical public ATS host"):
        SourceRegistryEntry.model_validate(values)


def test_source_config_generation_preserves_disabled_registry_entries() -> None:
    valid = entry("enabled", RegistryPlatform.GREENHOUSE, status=RegistryValidationStatus.VALID)
    disabled = entry(
        "disabled",
        RegistryPlatform.LEVER,
        enabled=False,
        status=RegistryValidationStatus.VALID,
    )
    registry = SourceRegistry(schema_version=1, sources=[valid, disabled])
    collection = CollectionSettings(
        request_timeout_seconds=20,
        user_agent="CareerOS fixture",
        max_retries=1,
        backoff_seconds=0,
        max_concurrency=2,
        max_response_bytes=5000,
    )

    generated = build_source_config(registry, collection)

    assert generated.greenhouse.boards == ["enabled"]
    assert generated.lever.enabled is False
    assert generated.lever.sites == []
    assert registry.sources[1].enabled is False


def test_registry_file_is_valid_curated_and_secret_free(tmp_path: Path) -> None:
    registry = load_yaml_model(Path("config/source_registry.yaml"), SourceRegistry)
    assert 75 <= len(registry.sources) <= 150
    assert all(
        source.validation_status == RegistryValidationStatus.VALID for source in registry.sources
    )
    assert any(source.identifier == "ciq" for source in registry.sources)

    output = tmp_path / "registry.yaml"
    write_yaml_model(output, registry)
    text = output.read_text(encoding="utf-8").lower()
    assert "authorization" not in text
    assert "cookie" not in text
    assert "api_key" not in text
    assert "webhook" not in text


def test_endpoint_templates_are_fixed_to_public_ats_hosts() -> None:
    assert endpoint_for(entry("board", RegistryPlatform.GREENHOUSE)) == (
        "https://boards-api.greenhouse.io/v1/boards/board/jobs"
    )
    assert endpoint_for(entry("site", RegistryPlatform.LEVER)) == (
        "https://api.lever.co/v0/postings/site?mode=json"
    )
    assert endpoint_for(entry("board", RegistryPlatform.ASHBY)) == (
        "https://api.ashbyhq.com/posting-api/job-board/board"
    )
