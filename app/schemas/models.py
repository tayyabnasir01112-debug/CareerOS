from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import (
    EligibilityStatus,
    EmploymentType,
    LocationType,
    PackageStatus,
    RunStatus,
)


class OrmSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CompanyBase(BaseModel):
    name: str
    normalized_name: str
    website_url: str | None = None
    raw_data: dict[str, Any] = Field(default_factory=dict)


class CompanyCreate(CompanyBase):
    pass


class CompanyRead(CompanyBase, OrmSchema):
    id: int
    created_at: datetime
    updated_at: datetime


class JobBase(BaseModel):
    source: str
    external_job_id: str
    fingerprint: str
    title: str
    normalized_title: str
    location: str | None = None
    location_type: LocationType = LocationType.UNKNOWN
    employment_type: EmploymentType = EmploymentType.UNKNOWN
    description: str
    source_url: str
    raw_source_data: dict[str, Any]
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    discovered_at: datetime
    collected_at: datetime
    salary_text: str | None = None
    compensation_currency: str | None = None
    compensation_min: float | None = None
    compensation_max: float | None = None
    compensation_period: str | None = None
    eligibility_status: EligibilityStatus = EligibilityStatus.PENDING
    eligibility_reasons: list[str] = Field(default_factory=list)


class JobCreate(JobBase):
    company_id: int


class JobRead(JobBase, OrmSchema):
    id: int
    company_id: int
    company: CompanyRead
    created_at: datetime
    updated_at: datetime


class JobEvaluationBase(BaseModel):
    job_id: int
    match_score: float = Field(ge=0, le=100)
    recommendation: str
    summary: str
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    model_name: str
    prompt_version: str
    evaluated_at: datetime


class JobEvaluationCreate(JobEvaluationBase):
    pass


class JobEvaluationRead(JobEvaluationBase, OrmSchema):
    id: int
    created_at: datetime
    updated_at: datetime


class ApplicationPackageBase(BaseModel):
    job_id: int
    status: PackageStatus = PackageStatus.PENDING
    output_directory: str | None = None
    cover_letter: str | None = None
    resume_notes: str | None = None
    interview_notes: str | None = None
    generated_at: datetime | None = None
    error_message: str | None = None


class ApplicationPackageCreate(ApplicationPackageBase):
    pass


class ApplicationPackageRead(ApplicationPackageBase, OrmSchema):
    id: int
    created_at: datetime
    updated_at: datetime


class CollectorRunBase(BaseModel):
    collector_name: str
    status: RunStatus = RunStatus.RUNNING
    started_at: datetime
    finished_at: datetime | None = None
    jobs_seen: int = 0
    jobs_created: int = 0
    jobs_updated: int = 0
    error_message: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class CollectorRunCreate(CollectorRunBase):
    pass


class CollectorRunRead(CollectorRunBase, OrmSchema):
    id: int


class PaginatedJobs(BaseModel):
    items: list[JobRead]
    total: int
    limit: int
    offset: int


class PaginatedRuns(BaseModel):
    items: list[CollectorRunRead]
    total: int
    limit: int
    offset: int
