import re

from pydantic import BaseModel, Field

from app.db.models import LocationEligibilityClassification, LocationType

ELIGIBLE_LOCATION_CLASSIFICATIONS = frozenset(
    {
        LocationEligibilityClassification.REMOTE_WORLDWIDE_ELIGIBLE,
        LocationEligibilityClassification.REMOTE_REGION_ELIGIBLE,
        LocationEligibilityClassification.PAKISTAN_ONSITE_ELIGIBLE,
        LocationEligibilityClassification.FOREIGN_ONSITE_WITH_RELOCATION,
        LocationEligibilityClassification.FOREIGN_HYBRID_WITH_RELOCATION,
    }
)


class LocationEligibilityInput(BaseModel):
    location: str | None = None
    location_type: LocationType = LocationType.UNKNOWN
    description: str = ""


class LocationEligibilityResult(BaseModel):
    classification: LocationEligibilityClassification
    evidence: list[str] = Field(default_factory=list, max_length=8)

    @property
    def is_explicitly_eligible(self) -> bool:
        return self.classification in ELIGIBLE_LOCATION_CLASSIFICATIONS


class LocationEligibilityService:
    _WORLDWIDE = re.compile(
        r"\b(?:worldwide|global(?:ly)? remote|remote global|work from anywhere|"
        r"remote\s*[-:]?\s*anywhere|anywhere in the world|location[- ]flexible)\b",
        re.IGNORECASE,
    )
    _PAKISTAN = re.compile(r"\bpakistan\b", re.IGNORECASE)
    _APAC = re.compile(r"\b(?:apac|asia[- ]pacific)\b", re.IGNORECASE)
    _EMEA = re.compile(r"\bemea\b", re.IGNORECASE)
    _REMOTE = re.compile(r"\bremote\b", re.IGNORECASE)
    _HYBRID = re.compile(r"\bhybrid\b", re.IGNORECASE)
    _RESTRICTED_REGION = re.compile(
        r"\b(?:u\.?s\.?|united states|canada|u\.?k\.?|united kingdom|"
        r"europe|european union|eu only|australia|singapore|india|poland|"
        r"latin america|latam)\b",
        re.IGNORECASE,
    )
    _RELOCATION = re.compile(
        r"\b(?:relocation (?:assistance|package|support)|international relocation support|"
        r"visa sponsorship|sponsor(?:ing|s)? (?:an? )?(?:employment )?visa|"
        r"work permit sponsorship)\b",
        re.IGNORECASE,
    )
    _RELOCATION_NEGATION = re.compile(
        r"\b(?:no|not|without|does not|do not|unable to)\b.{0,40}"
        r"\b(?:relocat|visa|sponsor|work permit)",
        re.IGNORECASE | re.DOTALL,
    )

    def classify(self, job: LocationEligibilityInput) -> LocationEligibilityResult:
        location = (job.location or "").strip()
        is_remote = job.location_type == LocationType.REMOTE or bool(self._REMOTE.search(location))
        is_hybrid = job.location_type == LocationType.HYBRID or bool(self._HYBRID.search(location))
        relocation = bool(self._RELOCATION.search(job.description)) and not bool(
            self._RELOCATION_NEGATION.search(job.description)
        )

        if is_remote:
            # Explicit location restrictions win over generic company
            # boilerplate such as "global team" or "work from anywhere".
            if self._WORLDWIDE.search(location):
                return self._result(
                    LocationEligibilityClassification.REMOTE_WORLDWIDE_ELIGIBLE,
                    "listing explicitly permits worldwide or location-flexible remote work",
                )
            if self._PAKISTAN.search(location):
                return self._result(
                    LocationEligibilityClassification.REMOTE_REGION_ELIGIBLE,
                    "remote listing explicitly permits Pakistan",
                )
            if self._APAC.search(location):
                return self._result(
                    LocationEligibilityClassification.REMOTE_REGION_ELIGIBLE,
                    "remote listing explicitly permits APAC applicants",
                )
            if self._EMEA.search(location):
                return self._result(
                    LocationEligibilityClassification.UNCLEAR,
                    "EMEA is stated but Pakistan eligibility is not explicit",
                )
            if self._RESTRICTED_REGION.search(location):
                return self._result(
                    LocationEligibilityClassification.REMOTE_LOCATION_RESTRICTED,
                    "remote listing is restricted to a named foreign country or region",
                )
            explicit_scope = re.sub(r"\b(?:remote|hybrid)\b|[\s:(),/-]+", "", location)
            if explicit_scope:
                return self._result(
                    LocationEligibilityClassification.REMOTE_LOCATION_RESTRICTED,
                    "remote listing is restricted to a named location",
                )
            if self._WORLDWIDE.search(job.description):
                return self._result(
                    LocationEligibilityClassification.REMOTE_WORLDWIDE_ELIGIBLE,
                    "listing text explicitly permits worldwide or location-flexible remote work",
                )
            if self._PAKISTAN.search(job.description) or self._APAC.search(job.description):
                return self._result(
                    LocationEligibilityClassification.REMOTE_REGION_ELIGIBLE,
                    "listing text explicitly permits Pakistan or APAC applicants",
                )
            if self._EMEA.search(job.description):
                return self._result(
                    LocationEligibilityClassification.UNCLEAR,
                    "EMEA is stated but Pakistan eligibility is not explicit",
                )
            return self._result(
                LocationEligibilityClassification.UNCLEAR,
                "remote scope is not explicit enough to confirm Pakistan eligibility",
            )

        if self._PAKISTAN.search(location):
            return self._result(
                LocationEligibilityClassification.PAKISTAN_ONSITE_ELIGIBLE,
                "listing location is in Pakistan",
            )

        if not location:
            return self._result(
                LocationEligibilityClassification.UNCLEAR,
                "listing location is undisclosed",
            )

        if is_hybrid:
            classification = (
                LocationEligibilityClassification.FOREIGN_HYBRID_WITH_RELOCATION
                if relocation
                else LocationEligibilityClassification.FOREIGN_HYBRID_WITHOUT_RELOCATION
            )
            evidence = (
                "foreign hybrid listing explicitly states relocation or visa support"
                if relocation
                else "foreign hybrid listing does not state relocation or visa support"
            )
            return self._result(classification, evidence)

        classification = (
            LocationEligibilityClassification.FOREIGN_ONSITE_WITH_RELOCATION
            if relocation
            else LocationEligibilityClassification.FOREIGN_ONSITE_WITHOUT_RELOCATION
        )
        evidence = (
            "foreign onsite listing explicitly states relocation or visa support"
            if relocation
            else "foreign onsite listing does not state relocation or visa support"
        )
        return self._result(classification, evidence)

    @staticmethod
    def _result(
        classification: LocationEligibilityClassification, evidence: str
    ) -> LocationEligibilityResult:
        return LocationEligibilityResult(classification=classification, evidence=[evidence])
