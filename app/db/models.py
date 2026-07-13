from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Enum,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.types import UTCDateTime


def utc_now() -> datetime:
    return datetime.now(UTC)


class EmploymentType(StrEnum):
    FULL_TIME = "full_time"
    CONTRACT = "contract"
    PART_TIME = "part_time"
    INTERNSHIP = "internship"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class LocationType(StrEnum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


class EligibilityStatus(StrEnum):
    PENDING = "pending"
    ELIGIBLE = "eligible"
    FLAGGED = "flagged"
    REJECTED = "rejected"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PackageStatus(StrEnum):
    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class Company(TimestampMixin, Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    website_url: Mapped[str | None] = mapped_column(String(2048))
    raw_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Job(TimestampMixin, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source", "external_job_id", name="source_external_job_id"),
        Index("ix_jobs_fingerprint", "fingerprint"),
        Index("ix_jobs_discovered_at", "discovered_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(100))
    external_job_id: Mapped[str] = mapped_column(String(255))
    fingerprint: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(500))
    normalized_title: Mapped[str] = mapped_column(String(500))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    location: Mapped[str | None] = mapped_column(String(500))
    location_type: Mapped[LocationType] = mapped_column(
        Enum(LocationType, native_enum=False), default=LocationType.UNKNOWN
    )
    employment_type: Mapped[EmploymentType] = mapped_column(
        Enum(EmploymentType, native_enum=False), default=EmploymentType.UNKNOWN
    )
    description: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(String(2048))
    raw_source_data: Mapped[dict[str, Any]] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    source_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    discovered_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    collected_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    salary_text: Mapped[str | None] = mapped_column(Text)
    compensation_currency: Mapped[str | None] = mapped_column(String(3))
    compensation_min: Mapped[float | None] = mapped_column(Float)
    compensation_max: Mapped[float | None] = mapped_column(Float)
    compensation_period: Mapped[str | None] = mapped_column(String(20))
    eligibility_status: Mapped[EligibilityStatus] = mapped_column(
        Enum(EligibilityStatus, native_enum=False), default=EligibilityStatus.PENDING
    )
    eligibility_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)

    company: Mapped[Company] = relationship(back_populates="jobs")
    evaluations: Mapped[list["JobEvaluation"]] = relationship(back_populates="job")
    application_packages: Mapped[list["ApplicationPackage"]] = relationship(back_populates="job")


class JobEvaluation(TimestampMixin, Base):
    __tablename__ = "job_evaluations"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    match_score: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(String(50))
    summary: Mapped[str | None] = mapped_column(Text)
    strengths: Mapped[list[str]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    model_name: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(50))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    evaluator_type: Mapped[str] = mapped_column(String(50), default="recruiter")
    structured_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    should_prepare_application: Mapped[bool] = mapped_column(default=False)
    input_hash: Mapped[str] = mapped_column(String(64), index=True)
    job_content_fingerprint: Mapped[str] = mapped_column(String(64))
    candidate_profile_fingerprint: Mapped[str] = mapped_column(String(64))
    preference_fingerprint: Mapped[str] = mapped_column(String(64))
    prompt_fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), index=True)
    api_response_id: Mapped[str | None] = mapped_column(String(255))
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    total_tokens: Mapped[int | None]
    duration_ms: Mapped[int | None]
    error_category: Mapped[str | None] = mapped_column(String(50))
    error_summary: Mapped[str | None] = mapped_column(String(500))

    job: Mapped[Job] = relationship(back_populates="evaluations")


class ApplicationPackage(TimestampMixin, Base):
    __tablename__ = "application_packages"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    status: Mapped[PackageStatus] = mapped_column(
        Enum(PackageStatus, native_enum=False), default=PackageStatus.PENDING
    )
    output_directory: Mapped[str | None] = mapped_column(String(2048))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    resume_notes: Mapped[str | None] = mapped_column(Text)
    interview_notes: Mapped[str | None] = mapped_column(Text)
    generated_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_message: Mapped[str | None] = mapped_column(Text)

    job: Mapped[Job] = relationship(back_populates="application_packages")


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    collector_name: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, native_enum=False), default=RunStatus.RUNNING
    )
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    jobs_seen: Mapped[int] = mapped_column(default=0)
    jobs_created: Mapped[int] = mapped_column(default=0)
    jobs_updated: Mapped[int] = mapped_column(default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
