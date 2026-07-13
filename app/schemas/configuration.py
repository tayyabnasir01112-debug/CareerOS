from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, StringConstraints

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
