from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.db.models import EmploymentType, LocationType


class CollectedJob(BaseModel):
    source: str
    external_job_id: str
    title: str
    company_name: str
    location: str | None = None
    location_type: LocationType = LocationType.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    description: str
    source_url: str
    raw_source_data: dict[str, Any]
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    collected_at: datetime
    salary_text: str | None = None
    compensation_currency: str | None = Field(default=None, min_length=3, max_length=3)
    compensation_min: float | None = Field(default=None, ge=0)
    compensation_max: float | None = Field(default=None, ge=0)
    compensation_period: str | None = None
