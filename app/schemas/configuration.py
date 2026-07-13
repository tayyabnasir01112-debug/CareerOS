from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AnyHttpUrl,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

CollectorIdentifier = Annotated[
    str,
    StringConstraints(
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9](?:[A-Za-z0-9_-]{0,98}[A-Za-z0-9])?$",
    ),
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateLocation(StrictModel):
    city: str
    country: str


class CandidateMobility(StrictModel):
    remote: bool
    relocation: bool


class Education(StrictModel):
    degree: str


class Experience(StrictModel):
    years: int = Field(ge=0)
    summary: str


class CandidateSkills(StrictModel):
    backend: list[str]
    automation: list[str]
    integrations: list[str]
    databases: list[str]
    delivery: list[str]
    secondary: list[str] = Field(default_factory=list)


class CandidateLinks(StrictModel):
    github: AnyHttpUrl
    portfolio: AnyHttpUrl
    linkedin: AnyHttpUrl
    website: AnyHttpUrl


class Candidate(StrictModel):
    name: str
    location: CandidateLocation
    mobility: CandidateMobility
    education: list[Education]
    experience: Experience
    skills: CandidateSkills
    achievements: list[str]
    links: CandidateLinks


class CandidateProfile(StrictModel):
    schema_version: Literal[1]
    candidate: Candidate


class LocationPreferences(StrictModel):
    allow_worldwide_remote: bool
    allow_pakistan_onsite: bool
    require_relocation_support_for_other_onsite: bool


class CompensationThreshold(StrictModel):
    currency: str
    minimum_monthly: float = Field(gt=0)
    preferred_monthly: float | None = Field(default=None, gt=0)


class ContractThreshold(StrictModel):
    currency: str
    minimum_hourly: float = Field(gt=0)


class CompensationPreferences(StrictModel):
    remote: CompensationThreshold
    pakistan: CompensationThreshold
    contract: ContractThreshold
    undisclosed: Literal["flag", "reject"]


class ExclusionPreferences(StrictModel):
    unpaid: bool
    commission_only: bool
    frontend_only: bool
    citizenship_restricted: bool


class JobPreferences(StrictModel):
    schema_version: Literal[1]
    employment_types: list[Literal["full_time", "contract"]]
    locations: LocationPreferences
    working_hours: list[Literal["pakistan", "europe", "us_eastern"]]
    compensation: CompensationPreferences
    maximum_listing_age_hours: int = Field(gt=0)
    minimum_match_score: int = Field(ge=0, le=100)
    maximum_application_packages_per_day: int = Field(gt=0)
    exclusions: ExclusionPreferences


class GreenhouseSource(StrictModel):
    enabled: bool = False
    boards: list[CollectorIdentifier] = Field(default_factory=list)


class LeverSource(StrictModel):
    enabled: bool = False
    sites: list[CollectorIdentifier] = Field(default_factory=list)


class AshbySource(StrictModel):
    enabled: bool = False
    boards: list[CollectorIdentifier] = Field(default_factory=list)


class CollectionSettings(StrictModel):
    request_timeout_seconds: int = Field(gt=0)
    user_agent: str
    max_retries: int = Field(default=2, ge=0, le=5)
    backoff_seconds: float = Field(default=0.5, ge=0, le=10)
    max_concurrency: int = Field(default=2, ge=1, le=5)
    max_response_bytes: int = Field(default=5_000_000, ge=1024, le=20_000_000)


class SourceConfig(StrictModel):
    schema_version: Literal[1]
    greenhouse: GreenhouseSource
    lever: LeverSource
    ashby: AshbySource
    collection: CollectionSettings


class RegistryPlatform(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"


class RegistryValidationStatus(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"


class RemoteRelevance(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class SourceRegistryEntry(StrictModel):
    company_name: str = Field(min_length=1, max_length=200)
    platform: RegistryPlatform
    identifier: CollectorIdentifier
    careers_url: AnyHttpUrl
    enabled: bool = False
    categories: list[str] = Field(min_length=1, max_length=12)
    remote_relevance: RemoteRelevance
    validation_status: RegistryValidationStatus = RegistryValidationStatus.PENDING
    has_active_jobs: bool | None = None
    last_validated_at: datetime | None = None
    validation_error: str | None = Field(default=None, max_length=300)
    consecutive_failures: int = Field(default=0, ge=0)
    cooldown_until: datetime | None = None

    @field_validator("careers_url")
    @classmethod
    def validate_careers_url(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.scheme != "https":
            raise ValueError("careers_url must use HTTPS")
        if value.username or value.password or value.query or value.fragment:
            raise ValueError(
                "careers_url must not include credentials, query parameters, or fragments"
            )
        return value

    @model_validator(mode="after")
    def validate_platform_careers_url(self) -> "SourceRegistryEntry":
        expected_host = {
            RegistryPlatform.GREENHOUSE: "job-boards.greenhouse.io",
            RegistryPlatform.LEVER: "jobs.lever.co",
            RegistryPlatform.ASHBY: "jobs.ashbyhq.com",
        }[self.platform]
        path_identifier = (self.careers_url.path or "").strip("/").split("/", maxsplit=1)[0]
        if (
            self.careers_url.host != expected_host
            or path_identifier.lower() != self.identifier.lower()
        ):
            raise ValueError(
                "careers_url must match the canonical public ATS host and source identifier"
            )
        return self


class SourceRegistry(StrictModel):
    schema_version: Literal[1]
    sources: list[SourceRegistryEntry]

    @model_validator(mode="after")
    def validate_unique_identifiers(self) -> "SourceRegistry":
        seen: set[tuple[RegistryPlatform, str]] = set()
        for source in self.sources:
            key = (source.platform, source.identifier.lower())
            if key in seen:
                raise ValueError(
                    f"duplicate source identifier: {source.platform.value}/{source.identifier}"
                )
            seen.add(key)
        return self
