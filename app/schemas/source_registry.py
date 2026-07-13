from pydantic import BaseModel, Field


class SourceValidationSummary(BaseModel):
    candidates_checked: int = 0
    valid_boards: int = 0
    invalid_boards: int = 0
    boards_with_active_jobs: int = 0
    boards_without_current_jobs: int = 0
    failures_by_platform: dict[str, int] = Field(default_factory=dict)
    enabled_source_count: int = 0
    skipped_by_cooldown: int = 0
