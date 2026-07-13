from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.db.session import Database
from app.schemas.configuration import CandidateProfile, JobPreferences
from app.schemas.evaluation import RecruiterEvaluationResult
from app.services.configuration import load_yaml_model
from app.services.evaluation_input import EvaluationInputBuilder
from tests.evaluation_helpers import add_job, provider_evaluation


def test_structured_schema_rejects_invalid_score_and_list_length() -> None:
    data = provider_evaluation().result.model_dump()
    data["match_score"] = 101
    data["matched_skills"] = [f"skill-{index}" for index in range(13)]

    with pytest.raises(ValidationError):
        RecruiterEvaluationResult.model_validate(data)


@pytest.mark.asyncio
async def test_prompt_uses_verified_facts_and_excludes_raw_and_sensitive_data(
    tmp_path: Path,
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'input.db'}")
    await database.create_schema()
    profile = load_yaml_model(Path("config/candidate_profile.yaml"), CandidateProfile)
    preferences = load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences)
    sensitive_description = (
        "Build Python backend systems. Required: FastAPI and SQLAlchemy. "
        "Contact phone: +1 202 555 0182. Local notes C:\\Users\\person\\private.txt. "
        "Use token=super-secret-value. Continue building reliable APIs and tests."
    )
    try:
        async with database.session_factory() as session:
            job = await add_job(session, external_id="input-1", description=sensitive_description)
            prepared = EvaluationInputBuilder(
                maximum_characters=18_000, model="fixture-model"
            ).build(job, profile, preferences)

            assert "7+ years of Python backend" in prepared.user_prompt
            assert "200+ production automation systems delivered" in prepared.user_prompt
            assert "must-not-enter-prompt" not in prepared.user_prompt
            assert "202 555 0182" not in prepared.user_prompt
            assert "private.txt" not in prepared.user_prompt
            assert "super-secret-value" not in prepared.user_prompt
            assert "employment_history" not in prepared.user_prompt
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_fingerprints_are_deterministic_and_component_specific(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'fingerprints.db'}")
    await database.create_schema()
    profile = load_yaml_model(Path("config/candidate_profile.yaml"), CandidateProfile)
    preferences = load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences)
    builder = EvaluationInputBuilder(maximum_characters=18_000, model="fixture-model")
    try:
        async with database.session_factory() as session:
            job = await add_job(session, external_id="fingerprint-1")
            first = builder.build(job, profile, preferences)
            second = builder.build(job, profile, preferences)
            changed_profile = profile.model_copy(deep=True)
            changed_profile.candidate.skills.backend.append("Verified New Skill")
            changed_preferences = preferences.model_copy(deep=True)
            changed_preferences.minimum_match_score = 80

            assert first.input_hash == second.input_hash
            assert first.job_content_fingerprint == second.job_content_fingerprint
            assert (
                first.candidate_profile_fingerprint
                != builder.build(job, changed_profile, preferences).candidate_profile_fingerprint
            )
            assert (
                first.preference_fingerprint
                != builder.build(job, profile, changed_preferences).preference_fingerprint
            )
            assert len(first.prompt_fingerprint) == 64

            job.description += " Material verified job change."
            assert (
                first.job_content_fingerprint
                != builder.build(job, profile, preferences).job_content_fingerprint
            )
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_oversized_description_is_deterministically_truncated(tmp_path: Path) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'truncate.db'}")
    await database.create_schema()
    settings = Settings(_env_file=None, openai_max_input_characters=7000)
    profile = load_yaml_model(Path("config/candidate_profile.yaml"), CandidateProfile)
    preferences = load_yaml_model(Path("config/job_preferences.yaml"), JobPreferences)
    description = "Responsibilities start. " + ("Python automation details. " * 2000) + "Terms end."
    try:
        async with database.session_factory() as session:
            job = await add_job(session, external_id="truncate-1", description=description)
            builder = EvaluationInputBuilder(
                maximum_characters=settings.openai_max_input_characters,
                model="fixture-model",
            )
            first = builder.build(job, profile, preferences)
            second = builder.build(job, profile, preferences)

            assert first.truncated is True
            assert "Responsibilities start" in first.user_prompt
            assert "Terms end" in first.user_prompt
            assert len(first.system_prompt) + len(first.user_prompt) <= 7000
            assert first.input_hash == second.input_hash
    finally:
        await database.dispose()
