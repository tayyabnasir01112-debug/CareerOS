from pathlib import Path

import httpx
import pytest
import yaml
from pydantic import ValidationError

from app.collectors.http import CollectorRequestError, ResilientHttpClient
from app.collectors.normalization import sanitize_raw_payload
from app.core.security import redact_sensitive_text
from app.schemas.configuration import SourceConfig
from scripts.scan_secrets import scan_paths


@pytest.mark.parametrize(
    "identifier",
    ["https://attacker.example/jobs", "../private", "company/name", "company?token=value"],
)
def test_collector_identifiers_reject_urls_and_path_traversal(identifier: str) -> None:
    data = yaml.safe_load(Path("config/source_config.yaml").read_text(encoding="utf-8"))
    data["greenhouse"]["boards"] = [identifier]

    with pytest.raises(ValidationError):
        SourceConfig.model_validate(data)


@pytest.mark.asyncio
async def test_http_response_size_is_bounded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'"' + (b"x" * 128) + b'"', request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = ResilientHttpClient(
            client,
            max_retries=0,
            backoff_seconds=0,
            max_concurrency=1,
            max_response_bytes=64,
        )
        with pytest.raises(CollectorRequestError, match="exceeded 64 bytes"):
            await http.get_json("https://public.example.test/jobs?token=hidden")


def test_sensitive_error_content_is_redacted() -> None:
    api_key = "sk-" + ("x" * 24)
    message = f"Bearer abc.def.ghi {api_key} https://public.example.test/jobs?token=secret-value"

    redacted = redact_sensitive_text(message)

    assert "abc.def.ghi" not in redacted
    assert api_key not in redacted
    assert "secret-value" not in redacted


def test_raw_payload_removes_transport_credentials_recursively() -> None:
    raw = {
        "id": "job-1",
        "headers": {"Authorization": "Bearer hidden"},
        "details": {"cookies": "session=hidden", "description": "Public description"},
    }

    sanitized = sanitize_raw_payload(raw)

    assert sanitized == {"id": "job-1", "details": {"description": "Public description"}}


def test_secret_scanner_reports_location_without_secret_value(tmp_path: Path) -> None:
    secret = "sk-" + ("z" * 24)
    candidate = tmp_path / "settings.txt"
    candidate.write_text(f"OPENAI_API_KEY={secret}\n", encoding="utf-8")

    findings = scan_paths([candidate])

    assert findings
    assert findings[0].path == candidate
    assert findings[0].line_number == 1
    assert secret not in repr(findings[0])
