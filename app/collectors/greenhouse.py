from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from app.collectors.base import JobCollector
from app.collectors.http import CollectorRequestError, ResilientHttpClient
from app.collectors.normalization import (
    html_to_text,
    humanize_identifier,
    normalize_employment_type,
    normalize_location_type,
    parse_datetime,
    sanitize_raw_payload,
    string_value,
)
from app.schemas.collector import CollectedJob


class GreenhouseCollector(JobCollector):
    def __init__(self, board: str, http: ResilientHttpClient) -> None:
        self.board = board
        self.http = http

    @property
    def name(self) -> str:
        return f"greenhouse:{self.board}"

    async def collect(self) -> AsyncIterator[CollectedJob]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{quote(self.board, safe='')}/jobs"
        payload = await self.http.get_json(url, params={"content": "true"})
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise CollectorRequestError(
                f"Greenhouse board '{self.board}' returned an invalid shape"
            )
        collected_at = datetime.now(UTC)
        for raw in payload["jobs"]:
            if not isinstance(raw, dict):
                continue
            yield self.normalize(raw, collected_at=collected_at)

    def normalize(self, raw: dict[str, Any], *, collected_at: datetime) -> CollectedJob:
        metadata = raw.get("metadata")
        employment = self._metadata_value(metadata, ("employment", "commitment", "job type"))
        workplace = self._metadata_value(metadata, ("workplace", "remote"))
        salary = self._metadata_value(metadata, ("salary", "compensation", "pay range"))
        location_data = raw.get("location")
        location = (
            string_value(location_data.get("name")) if isinstance(location_data, dict) else None
        )
        return CollectedJob(
            source="greenhouse",
            external_job_id=str(raw["id"]),
            source_url=str(raw["absolute_url"]),
            title=str(raw["title"]),
            company_name=humanize_identifier(self.board),
            location=location,
            location_type=normalize_location_type(workplace or location),
            employment_type=normalize_employment_type(employment),
            description=html_to_text(str(raw.get("content") or "")),
            salary_text=salary,
            published_at=None,
            source_updated_at=parse_datetime(raw.get("updated_at")),
            collected_at=collected_at,
            raw_source_data=sanitize_raw_payload(raw),
        )

    @staticmethod
    def _metadata_value(metadata: Any, names: tuple[str, ...]) -> str | None:
        if not isinstance(metadata, list):
            return None
        for item in metadata:
            if not isinstance(item, dict):
                continue
            key = str(item.get("name") or "").lower()
            if any(name in key for name in names):
                value = item.get("value")
                if isinstance(value, list):
                    return ", ".join(str(part) for part in value)
                return string_value(value)
        return None
