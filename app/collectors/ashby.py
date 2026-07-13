import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from app.collectors.base import JobCollector
from app.collectors.http import CollectorRequestError, ResilientHttpClient
from app.collectors.normalization import (
    float_value,
    html_to_text,
    humanize_identifier,
    normalize_employment_type,
    normalize_location_type,
    parse_datetime,
    sanitize_raw_payload,
    string_value,
)
from app.schemas.collector import CollectedJob


class AshbyCollector(JobCollector):
    def __init__(self, board: str, http: ResilientHttpClient) -> None:
        self.board = board
        self.http = http

    @property
    def name(self) -> str:
        return f"ashby:{self.board}"

    async def collect(self) -> AsyncIterator[CollectedJob]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{quote(self.board, safe='')}"
        payload = await self.http.get_json(url, params={"includeCompensation": "true"})
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            raise CollectorRequestError(f"Ashby board '{self.board}' returned an invalid shape")
        collected_at = datetime.now(UTC)
        for raw in payload["jobs"]:
            if isinstance(raw, dict) and raw.get("isListed", True):
                yield self.normalize(raw, collected_at=collected_at)

    def normalize(self, raw: dict[str, Any], *, collected_at: datetime) -> CollectedJob:
        source_url = str(raw["jobUrl"])
        compensation = raw.get("compensation")
        compensation = compensation if isinstance(compensation, dict) else {}
        salary_component = self._salary_component(compensation)
        external_id = (
            string_value(raw.get("id"))
            or hashlib.sha256(source_url.encode("utf-8")).hexdigest()[:32]
        )
        return CollectedJob(
            source="ashby",
            external_job_id=external_id,
            source_url=source_url,
            title=str(raw["title"]),
            company_name=humanize_identifier(self.board),
            location=string_value(raw.get("location")),
            location_type=normalize_location_type(
                string_value(raw.get("workplaceType")), is_remote=raw.get("isRemote") is True
            ),
            employment_type=normalize_employment_type(string_value(raw.get("employmentType"))),
            description=html_to_text(str(raw.get("descriptionHtml") or "")),
            salary_text=string_value(compensation.get("compensationTierSummary"))
            or string_value(compensation.get("scrapeableCompensationSalarySummary")),
            compensation_currency=string_value(salary_component.get("currencyCode")),
            compensation_min=float_value(salary_component.get("minValue")),
            compensation_max=float_value(salary_component.get("maxValue")),
            compensation_period=self._interval(salary_component.get("interval")),
            published_at=parse_datetime(raw.get("publishedAt")),
            source_updated_at=None,
            collected_at=collected_at,
            raw_source_data=sanitize_raw_payload(raw),
        )

    @staticmethod
    def _salary_component(compensation: dict[str, Any]) -> dict[str, Any]:
        components = compensation.get("summaryComponents")
        if isinstance(components, list):
            for component in components:
                if isinstance(component, dict) and component.get("compensationType") == "Salary":
                    return component
        return {}

    @staticmethod
    def _interval(value: Any) -> str | None:
        normalized = str(value or "").upper()
        if "YEAR" in normalized:
            return "year"
        if "MONTH" in normalized:
            return "month"
        if "HOUR" in normalized:
            return "hour"
        return None
