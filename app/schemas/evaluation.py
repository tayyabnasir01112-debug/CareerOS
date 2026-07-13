from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Recommendation(StrEnum):
    STRONG_APPLY = "strong_apply"
    APPLY = "apply"
    CONSIDER = "consider"
    SKIP = "skip"
    INELIGIBLE = "ineligible"


class RoleCategory(StrEnum):
    PYTHON_BACKEND = "python_backend"
    AUTOMATION = "automation"
    WEB_SCRAPING = "web_scraping"
    AI_AUTOMATION = "ai_automation"
    AI_ENGINEERING = "ai_engineering"
    INTEGRATION_ENGINEERING = "integration_engineering"
    DATA_ENGINEERING = "data_engineering"
    OTHER = "other"


class SeniorityAssessment(StrEnum):
    BELOW_LEVEL = "below_level"
    SUITABLE = "suitable"
    STRETCH = "stretch"
    SIGNIFICANTLY_OVERQUALIFIED = "significantly_overqualified"
    SIGNIFICANTLY_UNDERQUALIFIED = "significantly_underqualified"
    UNCLEAR = "unclear"


class CompensationAssessment(StrEnum):
    ABOVE_PREFERRED = "above_preferred"
    MEETS_PREFERRED = "meets_preferred"
    MEETS_MINIMUM = "meets_minimum"
    BELOW_MINIMUM = "below_minimum"
    UNDISCLOSED = "undisclosed"
    UNCLEAR = "unclear"


class LocationAssessment(StrEnum):
    ELIGIBLE = "eligible"
    LIKELY_ELIGIBLE = "likely_eligible"
    UNCLEAR = "unclear"
    INELIGIBLE = "ineligible"


class EvaluationStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    INELIGIBLE = "ineligible"


class EvaluationErrorCategory(StrEnum):
    CONFIGURATION_ERROR = "configuration_error"
    AUTHENTICATION_ERROR = "authentication_error"
    PERMISSION_ERROR = "permission_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    QUOTA_ERROR = "quota_error"
    TIMEOUT_ERROR = "timeout_error"
    TRANSIENT_PROVIDER_ERROR = "transient_provider_error"
    INVALID_STRUCTURED_OUTPUT = "invalid_structured_output"
    INPUT_TOO_LARGE = "input_too_large"
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


class RecruiterEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: Recommendation
    match_score: int = Field(ge=0, le=100)
    confidence_score: int = Field(ge=0, le=100)
    eligibility_confirmed: bool
    role_category: RoleCategory
    seniority_assessment: SeniorityAssessment
    compensation_assessment: CompensationAssessment
    location_assessment: LocationAssessment
    matched_skills: list[str] = Field(max_length=12)
    missing_required_skills: list[str] = Field(max_length=10)
    transferable_skills: list[str] = Field(max_length=8)
    strongest_verified_evidence: list[str] = Field(max_length=6)
    concerns: list[str] = Field(max_length=8)
    recommended_portfolio_projects: list[str] = Field(max_length=4)
    tailored_positioning: str = Field(min_length=1, max_length=800)
    evaluation_summary: str = Field(min_length=1, max_length=1200)
    should_prepare_application: bool


class PreparedEvaluationInput(BaseModel):
    job_id: int
    system_prompt: str
    user_prompt: str
    input_hash: str
    job_content_fingerprint: str
    candidate_profile_fingerprint: str
    preference_fingerprint: str
    prompt_fingerprint: str
    prompt_version: str
    model: str
    truncated: bool = False


class ProviderEvaluation(BaseModel):
    result: RecruiterEvaluationResult
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class EvaluationRunOptions(BaseModel):
    job_id: int | None = Field(default=None, gt=0)
    limit: int | None = Field(default=None, ge=1, le=100)
    minimum_rule_score: int = Field(default=75, ge=0, le=100)
    force: bool = False
    dry_run: bool = False


class DryRunEvaluation(BaseModel):
    job_id: int
    input_hash: str
    job_content_fingerprint: str
    truncated: bool


class EvaluationRunSummary(BaseModel):
    jobs_considered: int = 0
    evaluations_requested: int = 0
    evaluations_completed: int = 0
    cached_evaluations_reused: int = 0
    skipped_by_deterministic_eligibility: int = 0
    skipped_by_score_or_status_rules: int = 0
    failed_evaluations: int = 0
    daily_budget_remaining: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    errors: list[str] = Field(default_factory=list)
    dry_run_inputs: list[DryRunEvaluation] = Field(default_factory=list)


class EvaluationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    evaluator_type: str
    prompt_version: str
    model_name: str
    structured_result: RecruiterEvaluationResult | None
    match_score: float | None
    recommendation: str | None
    summary: str | None
    should_prepare_application: bool
    input_hash: str
    job_content_fingerprint: str
    candidate_profile_fingerprint: str
    preference_fingerprint: str
    prompt_fingerprint: str
    status: str
    api_response_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    duration_ms: int | None
    error_category: str | None
    error_summary: str | None
    evaluated_at: datetime
    created_at: datetime
    updated_at: datetime


class PaginatedEvaluations(BaseModel):
    items: list[EvaluationRead]
    total: int
    limit: int
    offset: int
