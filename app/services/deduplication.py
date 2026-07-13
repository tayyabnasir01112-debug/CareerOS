import hashlib
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FingerprintInput:
    title: str
    company: str
    location: str | None


class JobDeduplicationService:
    _NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")
    _COMPANY_SUFFIX = re.compile(
        r"\b(?:incorporated|corporation|company|limited|llc|ltd|inc|corp|co|pvt)\b"
    )
    _REMOTE = re.compile(r"\b(?:remote|worldwide|work from home|wfh)\b")

    @classmethod
    def normalize_text(cls, value: str) -> str:
        ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        return cls._NON_ALPHANUMERIC.sub(" ", ascii_value.lower()).strip()

    @classmethod
    def normalize_company(cls, value: str) -> str:
        return " ".join(cls._COMPANY_SUFFIX.sub(" ", cls.normalize_text(value)).split())

    @classmethod
    def normalize_location(cls, value: str | None) -> str:
        normalized = cls.normalize_text(value or "unspecified")
        if cls._REMOTE.search(normalized):
            return "remote"
        return normalized

    @classmethod
    def fingerprint(cls, job: FingerprintInput) -> str:
        identity = "|".join(
            (
                cls.normalize_text(job.title),
                cls.normalize_company(job.company),
                cls.normalize_location(job.location),
            )
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()
