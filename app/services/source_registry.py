import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import yaml

from app.core.security import redact_sensitive_text
from app.schemas.configuration import (
    AshbySource,
    CollectionSettings,
    GreenhouseSource,
    LeverSource,
    RegistryPlatform,
    RegistryValidationStatus,
    SourceConfig,
    SourceRegistry,
    SourceRegistryEntry,
)
from app.schemas.source_registry import SourceValidationSummary

_MAX_VALIDATION_RESPONSE_BYTES = 5_000_000
_VALIDATION_TTL = timedelta(days=7)
_FAILURE_COOLDOWN = timedelta(days=7)


def endpoint_for(source: SourceRegistryEntry) -> str:
    identifier = source.identifier
    if source.platform == RegistryPlatform.GREENHOUSE:
        return f"https://boards-api.greenhouse.io/v1/boards/{identifier}/jobs"
    if source.platform == RegistryPlatform.LEVER:
        return f"https://api.lever.co/v0/postings/{identifier}?mode=json"
    return f"https://api.ashbyhq.com/posting-api/job-board/{identifier}"


def _active_job_count(platform: RegistryPlatform, payload: Any) -> int:
    if platform == RegistryPlatform.LEVER:
        if not isinstance(payload, list):
            raise ValueError("Lever endpoint did not return a job list")
        return len(payload)
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise ValueError(f"{platform.value} endpoint did not return a jobs object")
    return len(payload["jobs"])


class SourceRegistryValidator:
    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        max_concurrency: int = 3,
        max_response_bytes: int = _MAX_VALIDATION_RESPONSE_BYTES,
        now: datetime | None = None,
    ) -> None:
        self.client = client
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_response_bytes = max_response_bytes
        self.now = (now or datetime.now(UTC)).astimezone(UTC)

    async def validate(
        self,
        registry: SourceRegistry,
        *,
        platform: RegistryPlatform | None = None,
        refresh: bool = False,
    ) -> SourceValidationSummary:
        selected = [
            item for item in registry.sources if platform is None or item.platform == platform
        ]
        due: list[SourceRegistryEntry] = []
        skipped = 0
        for source in selected:
            if not refresh and source.cooldown_until is not None:
                cooldown = source.cooldown_until
                if cooldown.tzinfo is None:
                    cooldown = cooldown.replace(tzinfo=UTC)
                if cooldown > self.now:
                    skipped += 1
                    continue
            if not refresh and source.last_validated_at is not None:
                validated = source.last_validated_at
                if validated.tzinfo is None:
                    validated = validated.replace(tzinfo=UTC)
                if self.now - validated < _VALIDATION_TTL:
                    skipped += 1
                    continue
            due.append(source)

        await asyncio.gather(*(self._validate_one(source) for source in due))
        return self._summary(registry, len(due), skipped)

    async def _validate_one(self, source: SourceRegistryEntry) -> None:
        try:
            payload = await self._get_json(endpoint_for(source))
            job_count = _active_job_count(source.platform, payload)
        except (httpx.HTTPError, ValueError) as exc:
            source.validation_status = RegistryValidationStatus.INVALID
            source.has_active_jobs = None
            source.enabled = False
            source.last_validated_at = self.now
            source.validation_error = redact_sensitive_text(str(exc))[:300]
            source.consecutive_failures += 1
            source.cooldown_until = self.now + _FAILURE_COOLDOWN
            return
        source.validation_status = RegistryValidationStatus.VALID
        source.has_active_jobs = job_count > 0
        source.last_validated_at = self.now
        source.validation_error = None
        source.consecutive_failures = 0
        source.cooldown_until = None

    async def _get_json(self, url: str) -> Any:
        async with self.semaphore, self.client.stream("GET", url) as response:
            if 300 <= response.status_code < 400:
                raise ValueError(f"public endpoint redirected with HTTP {response.status_code}")
            if response.status_code in {401, 403}:
                raise ValueError(
                    f"public endpoint requires authentication (HTTP {response.status_code})"
                )
            if response.status_code != 200:
                raise ValueError(f"public endpoint returned HTTP {response.status_code}")
            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.max_response_bytes:
                raise ValueError("public endpoint response exceeded the validation size limit")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > self.max_response_bytes:
                    raise ValueError("public endpoint response exceeded the validation size limit")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("public endpoint returned invalid JSON") from exc

    @staticmethod
    def _summary(
        registry: SourceRegistry, candidates_checked: int, skipped: int
    ) -> SourceValidationSummary:
        valid = [
            item
            for item in registry.sources
            if item.validation_status == RegistryValidationStatus.VALID
        ]
        invalid = [
            item
            for item in registry.sources
            if item.validation_status == RegistryValidationStatus.INVALID
        ]
        failures: dict[str, int] = {}
        for item in invalid:
            failures[item.platform.value] = failures.get(item.platform.value, 0) + 1
        return SourceValidationSummary(
            candidates_checked=candidates_checked,
            valid_boards=len(valid),
            invalid_boards=len(invalid),
            boards_with_active_jobs=sum(item.has_active_jobs is True for item in valid),
            boards_without_current_jobs=sum(item.has_active_jobs is False for item in valid),
            failures_by_platform=failures,
            enabled_source_count=sum(item.enabled for item in valid),
            skipped_by_cooldown=skipped,
        )


def build_source_config(
    registry: SourceRegistry,
    collection: CollectionSettings,
    *,
    now: datetime | None = None,
) -> SourceConfig:
    current = (now or datetime.now(UTC)).astimezone(UTC)

    def included(source: SourceRegistryEntry) -> bool:
        if not source.enabled or source.validation_status != RegistryValidationStatus.VALID:
            return False
        if source.cooldown_until is None:
            return True
        cooldown = source.cooldown_until
        if cooldown.tzinfo is None:
            cooldown = cooldown.replace(tzinfo=UTC)
        return cooldown <= current

    greenhouse = sorted(
        item.identifier
        for item in registry.sources
        if item.platform == RegistryPlatform.GREENHOUSE and included(item)
    )
    lever = sorted(
        item.identifier
        for item in registry.sources
        if item.platform == RegistryPlatform.LEVER and included(item)
    )
    ashby = sorted(
        item.identifier
        for item in registry.sources
        if item.platform == RegistryPlatform.ASHBY and included(item)
    )
    return SourceConfig(
        schema_version=1,
        greenhouse=GreenhouseSource(enabled=bool(greenhouse), boards=greenhouse),
        lever=LeverSource(enabled=bool(lever), sites=lever),
        ashby=AshbySource(enabled=bool(ashby), boards=ashby),
        collection=collection,
    )


def write_yaml_model(path: Path, model: SourceRegistry | SourceConfig) -> None:
    data = model.model_dump(mode="json", exclude_none=False)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
