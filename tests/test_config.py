from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.configuration import CandidateProfile, JobPreferences
from app.services.configuration import ConfigurationFileError, load_yaml_model


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAREEROS_ENVIRONMENT", "test")
    monkeypatch.setenv("CAREEROS_DATABASE_URL", "sqlite+aiosqlite:///./data/test.db")
    monkeypatch.setenv("CAREEROS_API_PAGE_SIZE", "25")

    settings = Settings(_env_file=None)

    assert settings.environment == "test"
    assert settings.database_url.endswith("data/test.db")
    assert settings.api_page_size == 25


def test_settings_reject_non_async_sqlite_url() -> None:
    with pytest.raises(ValidationError, match="async SQLite"):
        Settings(database_url="postgresql://localhost/careeros", _env_file=None)


def test_tracked_yaml_configuration_is_valid() -> None:
    profile = load_yaml_model(Path("config/candidate_profile.yaml"), CandidateProfile)
    preferences = load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences)

    assert profile.candidate.name == "Tayyab Nasir"
    assert preferences.maximum_listing_age_hours == 72
    assert preferences.compensation.remote.minimum_monthly == 1500


def test_missing_yaml_has_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationFileError, match="Configuration file not found"):
        load_yaml_model(tmp_path / "missing.yaml", CandidateProfile)


def test_openai_settings_use_unprefixed_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-credential")
    monkeypatch.setenv("OPENAI_RECRUITER_MODEL", "fixture-model")
    monkeypatch.setenv("OPENAI_MAX_EVALUATIONS_PER_RUN", "4")
    monkeypatch.setenv("OPENAI_MAX_EVALUATIONS_PER_DAY", "9")
    monkeypatch.setenv("OPENAI_MAX_INPUT_CHARACTERS", "8000")
    monkeypatch.setenv("OPENAI_REQUEST_TIMEOUT_SECONDS", "12")

    settings = Settings(_env_file=None)

    assert settings.openai_key_value() == "test-key-not-a-real-credential"
    assert settings.openai_recruiter_model == "fixture-model"
    assert settings.openai_max_evaluations_per_run == 4
    assert settings.openai_max_evaluations_per_day == 9
    assert settings.openai_max_input_characters == 8000
    assert settings.openai_request_timeout_seconds == 12
    assert "test-key-not-a-real-credential" not in repr(settings)
