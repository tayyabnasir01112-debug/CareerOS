from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from CAREEROS_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CAREEROS_",
        extra="ignore",
    )

    app_name: str = "CareerOS"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/careeros.db"
    candidate_profile_path: Path = Path("config/candidate_profile.yaml")
    job_preferences_path: Path = Path("config/job_preferences.yaml")
    source_config_path: Path = Path("config/source_config.yaml")
    api_page_size: int = Field(default=50, ge=1, le=200)

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite+aiosqlite:///"):
            raise ValueError("CareerOS currently requires an async SQLite database URL")
        return value


def load_settings() -> Settings:
    return Settings()
