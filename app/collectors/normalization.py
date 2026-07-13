import html
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from bs4 import BeautifulSoup

from app.db.models import EmploymentType, LocationType

_SENSITIVE_RAW_KEYS = {
    "authorization",
    "cookie",
    "cookies",
    "headers",
    "request_headers",
    "set-cookie",
}


def html_to_text(value: str) -> str:
    decoded = html.unescape(value)
    soup = BeautifulSoup(decoded, "html.parser")
    for element in soup(["script", "style", "noscript", "iframe", "svg", "form"]):
        element.decompose()
    text = soup.get_text(separator="\n")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", line).strip() for line in text.splitlines()]
    output: list[str] = []
    previous_blank = True
    for line in lines:
        if line:
            output.append(line)
            previous_blank = False
        elif not previous_blank:
            output.append("")
            previous_blank = True
    return "\n".join(output).strip()


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    candidate = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def humanize_identifier(identifier: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_]", identifier) if part)


def normalize_employment_type(value: str | None) -> EmploymentType:
    normalized = re.sub(r"[^a-z]", "", (value or "").lower())
    mapping = {
        "fulltime": EmploymentType.FULL_TIME,
        "contract": EmploymentType.CONTRACT,
        "contractor": EmploymentType.CONTRACT,
        "parttime": EmploymentType.PART_TIME,
        "intern": EmploymentType.INTERNSHIP,
        "internship": EmploymentType.INTERNSHIP,
        "temporary": EmploymentType.TEMPORARY,
        "temp": EmploymentType.TEMPORARY,
    }
    return mapping.get(normalized, EmploymentType.UNKNOWN)


def normalize_location_type(value: str | None, *, is_remote: bool = False) -> LocationType:
    if is_remote:
        return LocationType.REMOTE
    normalized = re.sub(r"[^a-z]", "", (value or "").lower())
    if normalized in {"remote", "workfromhome"}:
        return LocationType.REMOTE
    if normalized == "hybrid":
        return LocationType.HYBRID
    if normalized in {"onsite", "onlocation"}:
        return LocationType.ONSITE
    return LocationType.UNKNOWN


def string_value(value: Any) -> str | None:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def float_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def sanitize_raw_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): sanitize_raw_payload(item)
            for key, item in value.items()
            if str(key).lower() not in _SENSITIVE_RAW_KEYS
        }
    if isinstance(value, list):
        return [sanitize_raw_payload(item) for item in value]
    return value
