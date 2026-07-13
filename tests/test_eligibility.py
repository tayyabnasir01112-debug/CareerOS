from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.db.models import EmploymentType, LocationType
from app.schemas.configuration import JobPreferences
from app.services.configuration import load_yaml_model
from app.services.eligibility import (
    EligibilityDecision,
    EligibilityJob,
    EligibilityService,
)


@pytest.fixture
def service() -> EligibilityService:
    preferences = load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences)
    return EligibilityService(preferences)


def make_job(now: datetime, **overrides: object) -> EligibilityJob:
    values: dict[str, object] = {
        "title": "Senior Python Backend Engineer",
        "description": "Build reliable FastAPI services.",
        "employment_type": EmploymentType.FULL_TIME,
        "location": "Worldwide",
        "location_type": LocationType.REMOTE,
        "published_at": now - timedelta(hours=3),
        "compensation_currency": "USD",
        "compensation_min": 2000,
        "compensation_max": 2500,
        "compensation_period": "monthly",
    }
    values.update(overrides)
    return EligibilityJob.model_validate(values)


def test_matching_remote_job_is_eligible(service: EligibilityService) -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)

    result = service.evaluate(make_job(now), now=now)

    assert result.decision == EligibilityDecision.ELIGIBLE
    assert result.reasons == []


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"description": "This is an unpaid opportunity."}, "unpaid"),
        ({"title": "React Frontend Engineer"}, "frontend-only"),
        ({"description": "US citizens only."}, "citizenship"),
        ({"published_at": datetime(2026, 7, 9, tzinfo=UTC)}, "older than 72 hours"),
        ({"compensation_min": 900, "compensation_max": 1200}, "below USD 1500"),
    ],
)
def test_hard_exclusions_are_rejected(
    service: EligibilityService, overrides: dict[str, object], reason: str
) -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)

    result = service.evaluate(make_job(now, **overrides), now=now)

    assert result.decision == EligibilityDecision.REJECTED
    assert any(reason in item for item in result.reasons)


def test_undisclosed_compensation_is_flagged_not_rejected(
    service: EligibilityService,
) -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)
    job = make_job(
        now,
        compensation_currency=None,
        compensation_min=None,
        compensation_max=None,
        compensation_period=None,
    )

    result = service.evaluate(job, now=now)

    assert result.decision == EligibilityDecision.FLAGGED
    assert "compensation is undisclosed" in result.reasons


def test_undisclosed_employment_type_is_flagged_not_rejected(
    service: EligibilityService,
) -> None:
    now = datetime(2026, 7, 13, 12, tzinfo=UTC)

    result = service.evaluate(
        make_job(now, employment_type=EmploymentType.UNKNOWN),
        now=now,
    )

    assert result.decision == EligibilityDecision.FLAGGED
    assert "employment type is undisclosed" in result.reasons
