from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Company,
    EligibilityStatus,
    EmploymentType,
    Job,
    LocationType,
)
from app.schemas.evaluation import (
    CompensationAssessment,
    LocationAssessment,
    ProviderEvaluation,
    Recommendation,
    RecruiterEvaluationResult,
    RoleCategory,
    SeniorityAssessment,
)
from app.services.deduplication import FingerprintInput, JobDeduplicationService


def provider_evaluation(*, match_score: int = 88) -> ProviderEvaluation:
    return ProviderEvaluation(
        result=RecruiterEvaluationResult(
            recommendation=Recommendation.STRONG_APPLY,
            match_score=match_score,
            confidence_score=90,
            eligibility_confirmed=True,
            role_category=RoleCategory.PYTHON_BACKEND,
            seniority_assessment=SeniorityAssessment.SUITABLE,
            compensation_assessment=CompensationAssessment.MEETS_PREFERRED,
            location_assessment=LocationAssessment.ELIGIBLE,
            matched_skills=["Python", "FastAPI"],
            missing_required_skills=[],
            transferable_skills=["Flask"],
            strongest_verified_evidence=["7+ years of Python backend experience"],
            concerns=[],
            recommended_portfolio_projects=[],
            tailored_positioning="Lead with verified Python backend and automation delivery.",
            evaluation_summary="The verified profile strongly matches the backend requirements.",
            should_prepare_application=True,
        ),
        response_id="resp_fixture_123",
        input_tokens=120,
        output_tokens=80,
        total_tokens=200,
    )


async def add_job(
    session: AsyncSession,
    *,
    external_id: str,
    title: str = "Senior Python Backend Engineer",
    description: str | None = None,
    eligibility_status: EligibilityStatus = EligibilityStatus.ELIGIBLE,
    eligibility_reasons: list[str] | None = None,
) -> Job:
    company = await session.scalar(select(Company).where(Company.normalized_name == "example"))
    if company is None:
        company = Company(name="Example", normalized_name="example", raw_data={})
        session.add(company)
        await session.flush()
    now = datetime.now(UTC)
    body = description or (
        "Build and maintain Python FastAPI services, async integrations, SQLAlchemy data access, "
        "tests, APIs, and production automation. Required: strong Python and backend experience."
    )
    job = Job(
        source="fixture",
        external_job_id=external_id,
        fingerprint=JobDeduplicationService.fingerprint(
            FingerprintInput(title=title, company="Example", location="Remote")
        ),
        title=title,
        normalized_title=JobDeduplicationService.normalize_text(title),
        company=company,
        location="Remote",
        location_type=LocationType.REMOTE,
        employment_type=EmploymentType.FULL_TIME,
        description=body,
        source_url=f"https://jobs.example.test/{external_id}",
        raw_source_data={"secret_raw_marker": "must-not-enter-prompt"},
        published_at=now,
        source_updated_at=now,
        discovered_at=now,
        collected_at=now,
        salary_text="USD 2,000 monthly",
        compensation_currency="USD",
        compensation_min=2000,
        compensation_max=2500,
        compensation_period="month",
        eligibility_status=eligibility_status,
        eligibility_reasons=eligibility_reasons or [],
    )
    session.add(job)
    await session.flush()
    return job
