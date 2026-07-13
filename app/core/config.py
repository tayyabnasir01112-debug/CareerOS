import re
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from CAREEROS_* environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="CAREEROS_",
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "CareerOS"
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/careeros.db"
    candidate_profile_path: Path = Path("config/candidate_profile.yaml")
    job_preferences_path: Path = Path("config/job_preferences.yaml")
    source_config_path: Path = Path("config/source_config.yaml")
    api_page_size: int = Field(default=50, ge=1, le=200)
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_recruiter_model: str = Field(
        default="gpt-5.4-mini", validation_alias="OPENAI_RECRUITER_MODEL", min_length=1
    )
    openai_max_evaluations_per_run: int = Field(
        default=10, validation_alias="OPENAI_MAX_EVALUATIONS_PER_RUN", ge=1, le=100
    )
    openai_max_evaluations_per_day: int = Field(
        default=25, validation_alias="OPENAI_MAX_EVALUATIONS_PER_DAY", ge=1, le=1000
    )
    openai_max_input_characters: int = Field(
        default=18_000, validation_alias="OPENAI_MAX_INPUT_CHARACTERS", ge=2000, le=100_000
    )
    openai_request_timeout_seconds: float = Field(
        default=45, validation_alias="OPENAI_REQUEST_TIMEOUT_SECONDS", ge=1, le=300
    )
    openai_max_retries: int = Field(default=2, validation_alias="OPENAI_MAX_RETRIES", ge=0, le=5)
    openai_retry_base_seconds: float = Field(
        default=0.5, validation_alias="OPENAI_RETRY_BASE_SECONDS", ge=0, le=10
    )
    discord_webhook_url: SecretStr | None = Field(
        default=None, validation_alias="DISCORD_WEBHOOK_URL"
    )
    discord_notifications_enabled: bool = Field(
        default=True, validation_alias="DISCORD_NOTIFICATIONS_ENABLED"
    )
    discord_minimum_match_score: int = Field(
        default=75, validation_alias="DISCORD_MINIMUM_MATCH_SCORE", ge=0, le=100
    )
    discord_max_notifications_per_run: int = Field(
        default=5, validation_alias="DISCORD_MAX_NOTIFICATIONS_PER_RUN", ge=1, le=25
    )
    discord_request_timeout_seconds: float = Field(
        default=20, validation_alias="DISCORD_REQUEST_TIMEOUT_SECONDS", ge=1, le=120
    )
    discord_max_retries: int = Field(default=2, validation_alias="DISCORD_MAX_RETRIES", ge=0, le=5)
    discord_retry_base_seconds: float = Field(
        default=0.5, validation_alias="DISCORD_RETRY_BASE_SECONDS", ge=0, le=10
    )

    @field_validator("database_url")
    @classmethod
    def validate_async_database_url(cls, value: str) -> str:
        if not value.startswith("sqlite+aiosqlite:///"):
            raise ValueError("CareerOS currently requires an async SQLite database URL")
        return value

    @field_validator("discord_webhook_url")
    @classmethod
    def validate_discord_webhook_url(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return value
        webhook = value.get_secret_value().strip()
        if not re.fullmatch(
            r"https://(?:discord\.com|discordapp\.com)/api/webhooks/\d+/[A-Za-z0-9._-]+",
            webhook,
        ):
            raise ValueError("DISCORD_WEBHOOK_URL must be a standard HTTPS Discord webhook URL")
        return SecretStr(webhook)

    def openai_key_value(self) -> str | None:
        if self.openai_api_key is None:
            return None
        value = self.openai_api_key.get_secret_value().strip()
        return value or None

    def discord_webhook_value(self) -> str | None:
        if self.discord_webhook_url is None:
            return None
        value = self.discord_webhook_url.get_secret_value().strip()
        return value or None


def load_settings() -> Settings:
    return Settings()
