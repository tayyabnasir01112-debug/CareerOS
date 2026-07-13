import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel

from app.db.models import EmploymentType, LocationType
from app.schemas.configuration import JobPreferences


class EligibilityDecision(StrEnum):
    ELIGIBLE = "eligible"
    FLAGGED = "flagged"
    REJECTED = "rejected"


class EligibilityJob(BaseModel):
    title: str
    description: str
    employment_type: EmploymentType
    location: str | None = None
    location_type: LocationType
    published_at: datetime | None = None
    compensation_currency: str | None = None
    compensation_min: float | None = None
    compensation_max: float | None = None
    compensation_period: str | None = None
    relocation_supported: bool = False


class EligibilityResult(BaseModel):
    decision: EligibilityDecision
    reasons: list[str]


class EligibilityService:
    _UNPAID = re.compile(r"\b(?:unpaid|volunteer)\b", re.IGNORECASE)
    _COMMISSION_ONLY = re.compile(r"\b(?:commission[- ]only|100% commission)\b", re.IGNORECASE)
    _FRONTEND_TITLE = re.compile(r"\b(?:front[- ]?end|react|angular|vue)\b", re.IGNORECASE)
    _BACKEND_TITLE = re.compile(r"\b(?:back[- ]?end|full[- ]?stack|python|api)\b", re.IGNORECASE)
    _CITIZENSHIP = re.compile(
        r"\b(?:us|u\.s\.|american) citizens? only\b|"
        r"\b(?:must be|requires?) (?:a )?(?:us|u\.s\.) citizens?\b|"
        r"\bsecurity clearance required\b",
        re.IGNORECASE,
    )

    def __init__(self, preferences: JobPreferences) -> None:
        self.preferences = preferences

    def evaluate(self, job: EligibilityJob, *, now: datetime | None = None) -> EligibilityResult:
        rejected: list[str] = []
        flagged: list[str] = []
        content = f"{job.title}\n{job.description}"

        allowed_employment = set(self.preferences.employment_types)
        if job.employment_type == EmploymentType.UNKNOWN:
            flagged.append("employment type is undisclosed")
        elif job.employment_type.value not in allowed_employment:
            rejected.append(f"employment type '{job.employment_type.value}' is not included")

        exclusions = self.preferences.exclusions
        if exclusions.unpaid and self._UNPAID.search(content):
            rejected.append("job is unpaid")
        if exclusions.commission_only and self._COMMISSION_ONLY.search(content):
            rejected.append("job is commission-only")
        if (
            exclusions.frontend_only
            and self._FRONTEND_TITLE.search(job.title)
            and not self._BACKEND_TITLE.search(job.title)
        ):
            rejected.append("job is frontend-only")
        if exclusions.citizenship_restricted and self._CITIZENSHIP.search(content):
            rejected.append("job has a citizenship or clearance restriction")

        self._check_age(job, now or datetime.now(UTC), rejected, flagged)
        self._check_location(job, rejected)
        self._check_compensation(job, rejected, flagged)

        if rejected:
            return EligibilityResult(
                decision=EligibilityDecision.REJECTED, reasons=rejected + flagged
            )
        if flagged:
            return EligibilityResult(decision=EligibilityDecision.FLAGGED, reasons=flagged)
        return EligibilityResult(decision=EligibilityDecision.ELIGIBLE, reasons=[])

    def _check_age(
        self, job: EligibilityJob, now: datetime, rejected: list[str], flagged: list[str]
    ) -> None:
        if job.published_at is None:
            flagged.append("publication time is undisclosed")
            return
        published_at = job.published_at
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age_hours = (now.astimezone(UTC) - published_at.astimezone(UTC)).total_seconds() / 3600
        if age_hours > self.preferences.maximum_listing_age_hours:
            rejected.append(
                f"listing is older than {self.preferences.maximum_listing_age_hours} hours"
            )

    def _check_location(self, job: EligibilityJob, rejected: list[str]) -> None:
        locations = self.preferences.locations
        if job.location_type == LocationType.REMOTE:
            if not locations.allow_worldwide_remote:
                rejected.append("remote roles are not enabled")
            return
        is_pakistan = "pakistan" in (job.location or "").lower()
        if is_pakistan and locations.allow_pakistan_onsite:
            return
        if (
            job.location_type in {LocationType.ONSITE, LocationType.HYBRID}
            and locations.require_relocation_support_for_other_onsite
            and not job.relocation_supported
        ):
            rejected.append("onsite role outside Pakistan does not state relocation support")

    def _check_compensation(
        self, job: EligibilityJob, rejected: list[str], flagged: list[str]
    ) -> None:
        if job.compensation_currency is None or (
            job.compensation_min is None and job.compensation_max is None
        ):
            message = "compensation is undisclosed"
            if self.preferences.compensation.undisclosed == "reject":
                rejected.append(message)
            else:
                flagged.append(message)
            return

        if job.employment_type == EmploymentType.CONTRACT:
            minimum = self.preferences.compensation.contract.minimum_hourly
            currency = self.preferences.compensation.contract.currency
            period = "hour"
        elif job.location_type == LocationType.REMOTE:
            minimum = self.preferences.compensation.remote.minimum_monthly
            currency = self.preferences.compensation.remote.currency
            period = "month"
        else:
            minimum = self.preferences.compensation.pakistan.minimum_monthly
            currency = self.preferences.compensation.pakistan.currency
            period = "month"

        actual_period = (job.compensation_period or "").lower().rstrip("ly")
        if job.compensation_currency.upper() != currency or actual_period != period:
            flagged.append(f"compensation cannot be compared to {currency} per {period}")
            return
        upper_bound = (
            job.compensation_max if job.compensation_max is not None else job.compensation_min
        )
        if upper_bound is not None and upper_bound < minimum:
            rejected.append(f"maximum compensation is below {currency} {minimum:g} per {period}")
        elif job.compensation_min is not None and job.compensation_min < minimum:
            flagged.append(f"compensation range starts below {currency} {minimum:g} per {period}")
