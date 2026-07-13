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


class LeverCollector(JobCollector):
    def __init__(self, site: str, http: ResilientHttpClient) -> None:
        self.site = site
        self.http = http

    @property
    def name(self) -> str:
        return f"lever:{self.site}"

    async def collect(self) -> AsyncIterator[CollectedJob]:
        url = f"https://api.lever.co/v0/postings/{quote(self.site, safe='')}"
        payload = await self.http.get_json(url, params={"mode": "json"})
        if not isinstance(payload, list):
            raise CollectorRequestError(f"Lever site '{self.site}' returned an invalid shape")
        collected_at = datetime.now(UTC)
        for raw in payload:
            if isinstance(raw, dict):
                yield self.normalize(raw, collected_at=collected_at)

    def normalize(self, raw: dict[str, Any], *, collected_at: datetime) -> CollectedJob:
        categories = raw.get("categories")
        categories = categories if isinstance(categories, dict) else {}
        salary = raw.get("salaryRange")
        salary = salary if isinstance(salary, dict) else {}
        description_parts = [str(raw.get("description") or "")]
        additional = raw.get("additional")
        if additional:
            description_parts.append(str(additional))
        salary_description = string_value(raw.get("salaryDescriptionPlain"))
        return CollectedJob(
            source="lever",
            external_job_id=str(raw["id"]),
            source_url=str(raw["hostedUrl"]),
            title=str(raw["text"]),
            company_name=humanize_identifier(self.site),
            location=string_value(categories.get("location")),
            location_type=normalize_location_type(string_value(raw.get("workplaceType"))),
            employment_type=normalize_employment_type(string_value(categories.get("commitment"))),
            description=html_to_text("\n".join(description_parts)),
            salary_text=salary_description,
            compensation_currency=string_value(salary.get("currency")),
            compensation_min=float_value(salary.get("min")),
            compensation_max=float_value(salary.get("max")),
            compensation_period=string_value(salary.get("interval")),
            published_at=parse_datetime(raw.get("createdAt")),
            source_updated_at=None,
            collected_at=collected_at,
            raw_source_data=sanitize_raw_payload(raw),
        )
