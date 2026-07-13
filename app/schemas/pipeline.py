from typing import Literal

from pydantic import BaseModel, Field

CollectorPlatform = Literal["greenhouse", "lever", "ashby"]


class CollectionSummary(BaseModel):
    sources_attempted: int = 0
    sources_succeeded: int = 0
    sources_failed: int = 0
    jobs_fetched: int = 0
    jobs_inserted: int = 0
    jobs_updated: int = 0
    duplicates_skipped: int = 0
    jobs_eligible: int = 0
    jobs_flagged: int = 0
    jobs_rejected: int = 0
    errors: list[str] = Field(default_factory=list)
