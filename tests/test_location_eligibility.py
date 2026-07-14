import pytest

from app.db.models import LocationEligibilityClassification, LocationType
from app.services.location_eligibility import (
    LocationEligibilityInput,
    LocationEligibilityService,
)


@pytest.mark.parametrize(
    ("location", "location_type", "description", "expected"),
    [
        (
            "Singapore",
            LocationType.ONSITE,
            "Work from our Singapore office.",
            LocationEligibilityClassification.FOREIGN_ONSITE_WITHOUT_RELOCATION,
        ),
        (
            "Singapore",
            LocationType.ONSITE,
            "Work from Singapore. We provide visa sponsorship and relocation assistance.",
            LocationEligibilityClassification.FOREIGN_ONSITE_WITH_RELOCATION,
        ),
        (
            "Remote - US",
            LocationType.REMOTE,
            "This position is remote in the United States.",
            LocationEligibilityClassification.REMOTE_LOCATION_RESTRICTED,
        ),
        (
            "Remote: United States",
            LocationType.REMOTE,
            "Join our global remote team and work from anywhere in the United States.",
            LocationEligibilityClassification.REMOTE_LOCATION_RESTRICTED,
        ),
        (
            "Remote - India",
            LocationType.REMOTE,
            "Our worldwide organization supports flexible work.",
            LocationEligibilityClassification.REMOTE_LOCATION_RESTRICTED,
        ),
        (
            "Remote - Spain",
            LocationType.REMOTE,
            "We are a global company with distributed teams.",
            LocationEligibilityClassification.REMOTE_LOCATION_RESTRICTED,
        ),
        (
            "Worldwide Remote",
            LocationType.REMOTE,
            "Work from anywhere.",
            LocationEligibilityClassification.REMOTE_WORLDWIDE_ELIGIBLE,
        ),
        (
            "Remote - EMEA",
            LocationType.REMOTE,
            "Applicants must be located in EMEA.",
            LocationEligibilityClassification.UNCLEAR,
        ),
        (
            "Islamabad, Pakistan",
            LocationType.ONSITE,
            "Work in our Islamabad office.",
            LocationEligibilityClassification.PAKISTAN_ONSITE_ELIGIBLE,
        ),
        (
            "London, UK - Hybrid",
            LocationType.HYBRID,
            "Attend the London office three days each week.",
            LocationEligibilityClassification.FOREIGN_HYBRID_WITHOUT_RELOCATION,
        ),
    ],
)
def test_location_classification(
    location: str,
    location_type: LocationType,
    description: str,
    expected: LocationEligibilityClassification,
) -> None:
    result = LocationEligibilityService().classify(
        LocationEligibilityInput(
            location=location,
            location_type=location_type,
            description=description,
        )
    )

    assert result.classification == expected
    assert result.evidence
