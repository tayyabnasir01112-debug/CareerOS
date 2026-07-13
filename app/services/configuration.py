from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.schemas.configuration import (
    CandidateProfile,
    JobPreferences,
    SourceConfig,
    SourceRegistry,
)


class ConfigurationFileError(RuntimeError):
    pass


def load_yaml_model[ConfigurationT: BaseModel](
    path: Path, model: type[ConfigurationT]
) -> ConfigurationT:
    if not path.is_file():
        raise ConfigurationFileError(
            f"Configuration file not found: {path}. Copy the tracked example or set the "
            "corresponding CAREEROS_*_PATH environment variable."
        )
    try:
        with path.open(encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
    except yaml.YAMLError as exc:
        raise ConfigurationFileError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigurationFileError(f"Configuration file {path} must contain a YAML mapping")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigurationFileError(f"Invalid configuration in {path}: {exc}") from exc


def load_candidate_profile(settings: Settings) -> CandidateProfile:
    return load_yaml_model(settings.candidate_profile_path, CandidateProfile)


def load_job_preferences(settings: Settings) -> JobPreferences:
    return load_yaml_model(settings.job_preferences_path, JobPreferences)


def load_source_config(settings: Settings) -> SourceConfig:
    return load_yaml_model(settings.source_config_path, SourceConfig)


def load_source_registry(settings: Settings) -> SourceRegistry:
    return load_yaml_model(settings.source_registry_path, SourceRegistry)
