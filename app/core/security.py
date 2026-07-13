import re

_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"https?://(?:canary\.)?discord(?:app)?\.com/api/webhooks/[^\s]+", re.I),
        "[REDACTED_DISCORD_WEBHOOK]",
    ),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]+=*", re.I), "Bearer [REDACTED]"),
    (re.compile(r"(https?://[^\s?]+)\?[^\s]+", re.I), r"\1?[REDACTED_QUERY]"),
    (
        re.compile(
            r"\b(api[_-]?key|token|secret|password|cookie|authorization)\b"
            r"\s*[:=]\s*[^\s,;]+",
            re.I,
        ),
        r"\1=[REDACTED]",
    ),
)


def redact_sensitive_text(value: str) -> str:
    redacted = value
    for pattern, replacement in _REDACTIONS:
        redacted = pattern.sub(replacement, redacted)
    return redacted
