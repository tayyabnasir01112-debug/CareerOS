from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    EligibilityStatus,
    Job,
    JobEvaluation,
    LocationEligibilityClassification,
)
from app.schemas.evaluation import (
    EvaluationErrorCategory,
    EvaluationStatus,
    PreparedEvaluationInput,
    ProviderEvaluation,
    RecruiterEvaluationResult,
)
from app.services.evaluation_priority import MINIMUM_USEFUL_PRE_SCORE
from app.services.location_eligibility import ELIGIBLE_LOCATION_CLASSIFICATIONS


class EvaluationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def select_jobs(self, *, job_id: int | None, limit: int) -> list[Job]:
        successful_evaluation_exists = (
            select(JobEvaluation.id)
            .where(
                JobEvaluation.job_id == Job.id,
                JobEvaluation.status == EvaluationStatus.SUCCESS.value,
            )
            .exists()
        )
        eligibility_priority = case(
            (
                Job.eligibility_status.in_(
                    [EligibilityStatus.ELIGIBLE.value, EligibilityStatus.FLAGGED.value]
                ),
                0,
            ),
            (Job.eligibility_status == EligibilityStatus.REJECTED.value, 1),
            else_=2,
        )
        any_evaluation_exists = (
            select(JobEvaluation.id).where(JobEvaluation.job_id == Job.id).exists()
        )
        location_priority = case(
            (
                Job.location_classification
                == LocationEligibilityClassification.REMOTE_WORLDWIDE_ELIGIBLE,
                0,
            ),
            (
                Job.location_classification
                == LocationEligibilityClassification.REMOTE_REGION_ELIGIBLE,
                1,
            ),
            (
                Job.location_classification
                == LocationEligibilityClassification.PAKISTAN_ONSITE_ELIGIBLE,
                2,
            ),
            else_=3,
        )
        statement = (
            select(Job)
            .options(selectinload(Job.company))
            .order_by(
                eligibility_priority,
                location_priority,
                any_evaluation_exists,
                successful_evaluation_exists,
                func.coalesce(Job.published_at, Job.source_updated_at).desc(),
                Job.deterministic_pre_score.desc(),
                case((Job.compensation_currency.is_not(None), 0), else_=1),
                func.length(Job.description).desc(),
                Job.discovered_at.desc(),
                Job.id.desc(),
            )
            .limit(limit)
        )
        if job_id is not None:
            statement = statement.where(Job.id == job_id)
        else:
            statement = statement.where(
                Job.eligibility_status.in_([EligibilityStatus.ELIGIBLE, EligibilityStatus.FLAGGED]),
                Job.location_classification.in_(list(ELIGIBLE_LOCATION_CLASSIFICATIONS)),
                Job.deterministic_pre_score >= MINIMUM_USEFUL_PRE_SCORE,
            )
        return list((await self.session.scalars(statement)).all())

    async def find_cached(self, prepared: PreparedEvaluationInput) -> JobEvaluation | None:
        statement = (
            select(JobEvaluation)
            .where(
                JobEvaluation.job_id == prepared.job_id,
                JobEvaluation.status == EvaluationStatus.SUCCESS.value,
                JobEvaluation.job_content_fingerprint == prepared.job_content_fingerprint,
                JobEvaluation.candidate_profile_fingerprint
                == prepared.candidate_profile_fingerprint,
                JobEvaluation.preference_fingerprint == prepared.preference_fingerprint,
                JobEvaluation.prompt_fingerprint == prepared.prompt_fingerprint,
                JobEvaluation.prompt_version == prepared.prompt_version,
                JobEvaluation.model_name == prepared.model,
            )
            .order_by(JobEvaluation.created_at.desc())
            .limit(1)
        )
        return cast(JobEvaluation | None, await self.session.scalar(statement))

    async def count_daily_requests(self, now: datetime) -> int:
        utc_now = now.astimezone(UTC)
        start = datetime(utc_now.year, utc_now.month, utc_now.day, tzinfo=UTC)
        end = start + timedelta(days=1)
        statement = (
            select(func.count())
            .select_from(JobEvaluation)
            .where(
                JobEvaluation.evaluator_type == "recruiter",
                JobEvaluation.status.in_(
                    [EvaluationStatus.SUCCESS.value, EvaluationStatus.FAILED.value]
                ),
                JobEvaluation.created_at >= start,
                JobEvaluation.created_at < end,
            )
        )
        return int(await self.session.scalar(statement) or 0)

    async def save_success(
        self,
        prepared: PreparedEvaluationInput,
        provider_evaluation: ProviderEvaluation,
        duration_ms: int,
    ) -> JobEvaluation:
        result = provider_evaluation.result
        evaluation = self._base_evaluation(
            prepared,
            status=EvaluationStatus.SUCCESS,
            duration_ms=duration_ms,
        )
        evaluation.structured_result = result.model_dump(mode="json")
        evaluation.match_score = result.match_score
        evaluation.recommendation = result.recommendation.value
        evaluation.summary = result.evaluation_summary
        evaluation.strengths = result.matched_skills
        evaluation.gaps = result.missing_required_skills
        evaluation.should_prepare_application = result.should_prepare_application
        evaluation.api_response_id = provider_evaluation.response_id
        evaluation.input_tokens = provider_evaluation.input_tokens
        evaluation.output_tokens = provider_evaluation.output_tokens
        evaluation.total_tokens = provider_evaluation.total_tokens
        self.session.add(evaluation)
        await self.session.flush()
        return evaluation

    async def save_failure(
        self,
        prepared: PreparedEvaluationInput,
        category: EvaluationErrorCategory,
        summary: str,
        duration_ms: int,
    ) -> JobEvaluation:
        evaluation = self._base_evaluation(
            prepared,
            status=EvaluationStatus.FAILED,
            duration_ms=duration_ms,
        )
        evaluation.error_category = category.value
        evaluation.error_summary = summary[:500]
        self.session.add(evaluation)
        await self.session.flush()
        return evaluation

    async def save_ineligible(
        self,
        prepared: PreparedEvaluationInput,
        result: RecruiterEvaluationResult,
    ) -> JobEvaluation:
        evaluation = self._base_evaluation(
            prepared,
            status=EvaluationStatus.INELIGIBLE,
            duration_ms=0,
        )
        evaluation.structured_result = result.model_dump(mode="json")
        evaluation.match_score = result.match_score
        evaluation.recommendation = result.recommendation.value
        evaluation.summary = result.evaluation_summary
        evaluation.strengths = result.matched_skills
        evaluation.gaps = result.missing_required_skills
        self.session.add(evaluation)
        await self.session.flush()
        return evaluation

    def _base_evaluation(
        self,
        prepared: PreparedEvaluationInput,
        *,
        status: EvaluationStatus,
        duration_ms: int,
    ) -> JobEvaluation:
        return JobEvaluation(
            job_id=prepared.job_id,
            evaluator_type="recruiter",
            prompt_version=prepared.prompt_version,
            model_name=prepared.model,
            input_hash=prepared.input_hash,
            job_content_fingerprint=prepared.job_content_fingerprint,
            candidate_profile_fingerprint=prepared.candidate_profile_fingerprint,
            preference_fingerprint=prepared.preference_fingerprint,
            prompt_fingerprint=prepared.prompt_fingerprint,
            status=status.value,
            duration_ms=duration_ms,
            evaluated_at=datetime.now(UTC),
            strengths=[],
            gaps=[],
        )

    async def list_evaluations(self, *, limit: int, offset: int) -> tuple[list[JobEvaluation], int]:
        statement = (
            select(JobEvaluation)
            .order_by(JobEvaluation.created_at.desc(), JobEvaluation.id.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await self.session.scalars(statement)).all())
        total = int(await self.session.scalar(select(func.count()).select_from(JobEvaluation)) or 0)
        return items, total

    async def get_evaluation(self, evaluation_id: int) -> JobEvaluation | None:
        return cast(JobEvaluation | None, await self.session.get(JobEvaluation, evaluation_id))

    async def get_latest_for_job(self, job_id: int) -> JobEvaluation | None:
        statement = (
            select(JobEvaluation)
            .where(JobEvaluation.job_id == job_id)
            .order_by(JobEvaluation.created_at.desc(), JobEvaluation.id.desc())
            .limit(1)
        )
        return cast(JobEvaluation | None, await self.session.scalar(statement))
