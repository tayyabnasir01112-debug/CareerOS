from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.pipeline import CollectorPlatform


class NotificationErrorCategory(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    AUTHENTICATION_ERROR = "authentication_error"
    INVALID_WEBHOOK_ERROR = "invalid_webhook_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    TIMEOUT_ERROR = "timeout_error"
    TRANSIENT_PROVIDER_ERROR = "transient_provider_error"
    INVALID_RESPONSE_ERROR = "invalid_response_error"
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


class DiscordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(default="CareerOS", max_length=80)
    allowed_mentions: dict[str, list[str]] = Field(default_factory=lambda: {"parse": list[str]()})
    embeds: list[dict[str, Any]] = Field(min_length=1, max_length=10)


class NotificationDelivery(BaseModel):
    provider_response_id: str | None = None
    attempts: int = Field(default=1, ge=1)


class NotificationRunSummary(BaseModel):
    notifications_sent: int = 0
    notifications_skipped: int = 0
    notification_failures: int = 0
    errors: list[str] = Field(default_factory=list)


class PipelineRunOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: CollectorPlatform | None = None
    all_sources: bool = False
    limit: int | None = Field(default=None, ge=1, le=100)
    dry_run: bool = False
    no_notify: bool = False
    force_evaluation: bool = False

    @model_validator(mode="after")
    def validate_source_selection(self) -> "PipelineRunOptions":
        if self.source is not None and self.all_sources:
            raise ValueError("source and all_sources are mutually exclusive")
        return self


class CareerPipelineSummary(BaseModel):
    jobs_fetched: int = 0
    jobs_inserted: int = 0
    jobs_updated: int = 0
    duplicates_skipped: int = 0
    jobs_eligible: int = 0
    jobs_evaluated: int = 0
    cached_evaluations_reused: int = 0
    evaluations_failed: int = 0
    notifications_sent: int = 0
    notifications_skipped: int = 0
    notification_failures: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    daily_evaluation_budget_remaining: int = 0
    errors: list[str] = Field(default_factory=list)


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    evaluation_id: int
    channel_type: str
    evaluation_fingerprint: str
    status: str
    provider_response_id: str | None
    attempt_count: int
    error_category: str | None
    error_summary: str | None
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaginatedNotifications(BaseModel):
    items: list[NotificationRead]
    total: int
    limit: int
    offset: int
