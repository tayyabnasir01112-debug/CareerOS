import re
from datetime import UTC, datetime

from app.db.models import EmploymentType, Job, LocationEligibilityClassification
from app.schemas.configuration import CandidateProfile, JobPreferences
from app.services.location_eligibility import ELIGIBLE_LOCATION_CLASSIFICATIONS

MINIMUM_USEFUL_PRE_SCORE = 60


class EvaluationPriorityService:
    _TARGET_TITLE = re.compile(
        r"\b(?:python|backend|back-end|automation|scraping|data engineer|"
        r"integration engineer|applied ai|ai engineer|llm|developer tooling|api engineer|"
        r"software engineer(?:ing)?|applications? engineer|platform engineer|solutions engineer)\b",
        re.IGNORECASE,
    )

    def __init__(self, profile: CandidateProfile, preferences: JobPreferences) -> None:
        self.preferences = preferences
        skill_groups = profile.candidate.skills.model_dump().values()
        self.skills = {
            skill.lower() for group in skill_groups for skill in group if len(skill.strip()) >= 3
        }

    def score(self, job: Job, *, now: datetime | None = None) -> int:
        reference = (now or datetime.now(UTC)).astimezone(UTC)
        content = f"{job.title}\n{job.description}".lower()
        title_score = 25 if self._TARGET_TITLE.search(job.title) else 0
        overlaps = sum(1 for skill in self.skills if skill in content)
        # Description boilerplate can mention many verified skills. Do not let
        # it alone promote a clearly unrelated title into the paid queue.
        skill_score = min(20, overlaps * 4) if title_score else 0
        location_score = self._location_score(job.location_classification)
        recency_score = self._recency_score(job, reference)
        employment_score = (
            10
            if job.employment_type.value in self.preferences.employment_types
            else 3
            if job.employment_type == EmploymentType.UNKNOWN
            else 0
        )
        compensation_score = (
            5
            if job.compensation_currency
            and (job.compensation_min is not None or job.compensation_max is not None)
            else 0
        )
        description_score = (
            5 if len(job.description) >= 1000 else 3 if len(job.description) >= 300 else 0
        )
        return min(
            100,
            title_score
            + skill_score
            + location_score
            + recency_score
            + employment_score
            + compensation_score
            + description_score,
        )

    @staticmethod
    def _location_score(classification: LocationEligibilityClassification) -> int:
        return {
            LocationEligibilityClassification.REMOTE_WORLDWIDE_ELIGIBLE: 20,
            LocationEligibilityClassification.REMOTE_REGION_ELIGIBLE: 18,
            LocationEligibilityClassification.PAKISTAN_ONSITE_ELIGIBLE: 15,
            LocationEligibilityClassification.FOREIGN_ONSITE_WITH_RELOCATION: 10,
            LocationEligibilityClassification.FOREIGN_HYBRID_WITH_RELOCATION: 10,
        }.get(classification, 0)

    @staticmethod
    def _recency_score(job: Job, now: datetime) -> int:
        posted = job.published_at or job.source_updated_at
        if posted is None:
            return 3
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=UTC)
        age = (now - posted.astimezone(UTC)).total_seconds() / 3600
        if age <= 24:
            return 15
        if age <= 48:
            return 10
        if age <= 72:
            return 5
        return 0


def has_confirmed_eligible_location(job: Job) -> bool:
    return job.location_classification in ELIGIBLE_LOCATION_CLASSIFICATIONS
