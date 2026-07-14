import hashlib
import json
import re
from pathlib import Path
from typing import Any

from app.collectors.normalization import html_to_text
from app.core.security import redact_sensitive_text
from app.db.models import EligibilityStatus, Job
from app.schemas.configuration import CandidateProfile, JobPreferences
from app.schemas.evaluation import PreparedEvaluationInput

PROMPT_VERSION = "recruiter_v2"
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LABELED_PHONE = re.compile(
    r"\b(?:phone|telephone|tel|mobile)\s*[:=]\s*\+?[\d().\s-]{7,25}", re.IGNORECASE
)
_INTERNATIONAL_PHONE = re.compile(r"\+\d[\d(). -]{7,20}\d")
_WINDOWS_PATH = re.compile(r"\b[A-Za-z]:\\[^\s]+")
_POSIX_HOME_PATH = re.compile(r"/(?:Users|home)/[^\s]+")


class EvaluationInputError(RuntimeError):
    pass


def canonical_fingerprint(value: Any) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def sanitize_prompt_text(value: str) -> str:
    cleaned = html_to_text(value)
    cleaned = _CONTROL_CHARACTERS.sub("", cleaned)
    cleaned = _LABELED_PHONE.sub("[REDACTED_PHONE]", cleaned)
    cleaned = _INTERNATIONAL_PHONE.sub("[REDACTED_PHONE]", cleaned)
    cleaned = _WINDOWS_PATH.sub("[REDACTED_LOCAL_PATH]", cleaned)
    cleaned = _POSIX_HOME_PATH.sub("[REDACTED_LOCAL_PATH]", cleaned)
    return redact_sensitive_text(cleaned)


def sanitize_prompt_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): sanitize_prompt_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_prompt_value(item) for item in value]
    if isinstance(value, str):
        return sanitize_prompt_text(value)
    return value


def truncate_middle(value: str, maximum: int) -> tuple[str, bool]:
    if len(value) <= maximum:
        return value, False
    marker = "\n\n[DESCRIPTION TRUNCATED DETERMINISTICALLY]\n\n"
    if maximum <= len(marker):
        return value[:maximum], True
    available = maximum - len(marker)
    head = int(available * 0.7)
    tail = available - head
    return f"{value[:head]}{marker}{value[-tail:]}", True


class EvaluationInputBuilder:
    def __init__(self, *, maximum_characters: int, model: str) -> None:
        self.maximum_characters = maximum_characters
        self.model = model
        prompt_root = Path(__file__).parents[1] / "prompts" / "recruiter"
        self.system_prompt = (prompt_root / "system_v2.txt").read_text(encoding="utf-8").strip()
        self.user_template = (prompt_root / "user_v2.txt").read_text(encoding="utf-8").strip()
        self.prompt_fingerprint = canonical_fingerprint(
            {
                "version": PROMPT_VERSION,
                "system": self.system_prompt,
                "user": self.user_template,
            }
        )

    def build(
        self,
        job: Job,
        candidate_profile: CandidateProfile,
        preferences: JobPreferences,
    ) -> PreparedEvaluationInput:
        candidate_data = sanitize_prompt_value(candidate_profile.candidate.model_dump(mode="json"))
        preference_data = sanitize_prompt_value(preferences.model_dump(mode="json"))
        description = sanitize_prompt_text(job.description)
        job_data = self._job_data(job, description)
        eligibility_data = sanitize_prompt_value(
            {
                "status": job.eligibility_status.value,
                "reasons": job.eligibility_reasons,
                "rule_score": self.rule_score(job.eligibility_status),
                "location_classification": job.location_classification.value,
                "location_evidence": job.location_evidence,
                "deterministic_pre_score": job.deterministic_pre_score,
            }
        )
        portfolio_data = sanitize_prompt_value(
            {
                "verified_achievements": candidate_profile.candidate.achievements,
                "public_professional_links": candidate_profile.candidate.links.model_dump(
                    mode="json"
                ),
                "verified_projects": [],
            }
        )
        user_prompt = self._render(
            job_data,
            candidate_data,
            preference_data,
            eligibility_data,
            portfolio_data,
        )
        truncated = len(self.system_prompt) + len(user_prompt) > self.maximum_characters
        if truncated:
            original_description = description
            job_data["description"] = ""
            smallest_prompt = self._render(
                job_data,
                candidate_data,
                preference_data,
                eligibility_data,
                portfolio_data,
            )
            if len(self.system_prompt) + len(smallest_prompt) > self.maximum_characters:
                raise EvaluationInputError(
                    "Verified profile, preferences, and required job metadata exceed the "
                    "configured input character limit"
                )
            low = 0
            high = len(original_description)
            best_prompt = smallest_prompt
            while low <= high:
                midpoint = (low + high) // 2
                candidate_description, _ = truncate_middle(original_description, midpoint)
                job_data["description"] = candidate_description
                candidate_prompt = self._render(
                    job_data,
                    candidate_data,
                    preference_data,
                    eligibility_data,
                    portfolio_data,
                )
                if len(self.system_prompt) + len(candidate_prompt) <= self.maximum_characters:
                    best_prompt = candidate_prompt
                    low = midpoint + 1
                else:
                    high = midpoint - 1
            user_prompt = best_prompt

        job_fingerprint = canonical_fingerprint(
            self._job_data(job, sanitize_prompt_text(job.description))
        )
        candidate_fingerprint = canonical_fingerprint(candidate_data)
        preference_fingerprint = canonical_fingerprint(preference_data)
        input_hash = canonical_fingerprint(
            {"system_prompt": self.system_prompt, "user_prompt": user_prompt}
        )
        return PreparedEvaluationInput(
            job_id=job.id,
            system_prompt=self.system_prompt,
            user_prompt=user_prompt,
            input_hash=input_hash,
            job_content_fingerprint=job_fingerprint,
            candidate_profile_fingerprint=candidate_fingerprint,
            preference_fingerprint=preference_fingerprint,
            prompt_fingerprint=self.prompt_fingerprint,
            prompt_version=PROMPT_VERSION,
            model=self.model,
            truncated=truncated,
        )

    @staticmethod
    def rule_score(status: EligibilityStatus) -> int:
        if status == EligibilityStatus.ELIGIBLE:
            return 100
        if status == EligibilityStatus.FLAGGED:
            return 75
        return 0

    @staticmethod
    def _job_data(job: Job, description: str) -> dict[str, Any]:
        return {
            "title": sanitize_prompt_text(job.title),
            "company": sanitize_prompt_text(job.company.name),
            "location": sanitize_prompt_text(job.location or "undisclosed"),
            "location_type": job.location_type.value,
            "location_classification": job.location_classification.value,
            "location_evidence": job.location_evidence,
            "employment_type": job.employment_type.value,
            "description": description,
            "salary_text": sanitize_prompt_text(job.salary_text or "undisclosed"),
            "compensation_currency": job.compensation_currency,
            "compensation_min": job.compensation_min,
            "compensation_max": job.compensation_max,
            "compensation_period": job.compensation_period,
            "published_at": job.published_at.isoformat() if job.published_at else None,
            "source_updated_at": (
                job.source_updated_at.isoformat() if job.source_updated_at else None
            ),
        }

    def _render(
        self,
        job_data: dict[str, Any],
        candidate_data: dict[str, Any],
        preference_data: dict[str, Any],
        eligibility_data: dict[str, Any],
        portfolio_data: dict[str, Any],
    ) -> str:
        def compact(value: Any) -> str:
            return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

        return self.user_template.format(
            job_json=compact(job_data),
            candidate_json=compact(candidate_data),
            preferences_json=compact(preference_data),
            eligibility_json=compact(eligibility_data),
            portfolio_json=compact(portfolio_data),
        )
