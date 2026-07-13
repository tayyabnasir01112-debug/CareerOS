from datetime import UTC, datetime

import httpx
import pytest

from app.collectors.ashby import AshbyCollector
from app.collectors.greenhouse import GreenhouseCollector
from app.collectors.http import ResilientHttpClient
from app.collectors.lever import LeverCollector
from app.collectors.normalization import html_to_text
from app.db.models import EmploymentType, LocationType


def make_http(payload: object) -> tuple[httpx.AsyncClient, ResilientHttpClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client, ResilientHttpClient(client, max_retries=0, backoff_seconds=0, max_concurrency=1)


@pytest.mark.asyncio
async def test_http_retries_a_transient_server_failure() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        status = 503 if attempts == 1 else 200
        return httpx.Response(status, json={"jobs": []}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        http = ResilientHttpClient(client, max_retries=1, backoff_seconds=0, max_concurrency=1)
        result = await http.get_json("https://public.example.test/jobs")

    assert result == {"jobs": []}
    assert attempts == 2


def test_html_to_text_preserves_structure_and_removes_active_content() -> None:
    source = """
    <style>.hidden { display: none }</style><h2>Requirements</h2>
    <ul><li>Python</li><li>FastAPI</li></ul>
    <script>track('candidate')</script><p>USD 2,000 monthly</p>
    """

    cleaned = html_to_text(source)

    assert cleaned == "Requirements\n\nPython\nFastAPI\n\nUSD 2,000 monthly"
    assert "track" not in cleaned


@pytest.mark.asyncio
async def test_greenhouse_normalization() -> None:
    payload = {
        "jobs": [
            {
                "id": 101,
                "title": "Python Engineer",
                "updated_at": "2026-07-13T10:00:00Z",
                "location": {"name": "Remote"},
                "absolute_url": "https://boards.greenhouse.io/example/jobs/101",
                "content": "&lt;h2&gt;Role&lt;/h2&gt;&lt;p&gt;Build APIs.&lt;/p&gt;",
                "metadata": [
                    {"name": "Employment Type", "value": "Full Time"},
                    {"name": "Salary", "value": "USD 2,000 monthly"},
                ],
            }
        ]
    }
    client, http = make_http(payload)
    async with client:
        jobs = [job async for job in GreenhouseCollector("example-company", http).collect()]

    assert jobs[0].external_job_id == "101"
    assert jobs[0].company_name == "Example Company"
    assert jobs[0].description == "Role\nBuild APIs."
    assert jobs[0].employment_type == EmploymentType.FULL_TIME
    assert jobs[0].location_type == LocationType.REMOTE
    assert jobs[0].salary_text == "USD 2,000 monthly"
    assert jobs[0].source_updated_at == datetime(2026, 7, 13, 10, tzinfo=UTC)


@pytest.mark.asyncio
async def test_lever_normalization() -> None:
    payload = [
        {
            "id": "lever-101",
            "text": "Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/example/lever-101",
            "createdAt": 1783936800000,
            "categories": {"location": "Worldwide", "commitment": "Full-time"},
            "workplaceType": "remote",
            "description": "<h2>What you do</h2><p>Build services.</p>",
            "additional": "<p>Inclusive workplace.</p>",
            "salaryRange": {"currency": "USD", "interval": "month", "min": 2000, "max": 2500},
            "salaryDescriptionPlain": "USD 2,000-2,500 monthly",
        }
    ]
    client, http = make_http(payload)
    async with client:
        jobs = [job async for job in LeverCollector("example-company", http).collect()]

    assert jobs[0].employment_type == EmploymentType.FULL_TIME
    assert jobs[0].location_type == LocationType.REMOTE
    assert jobs[0].compensation_min == 2000
    assert jobs[0].compensation_period == "month"
    assert "Inclusive workplace." in jobs[0].description


@pytest.mark.asyncio
async def test_ashby_normalization() -> None:
    payload = {
        "apiVersion": "1",
        "jobs": [
            {
                "title": "Automation Engineer",
                "location": "Islamabad, Pakistan",
                "isListed": True,
                "isRemote": False,
                "workplaceType": "OnSite",
                "descriptionHtml": "<h2>About</h2><p>Build automations.</p>",
                "publishedAt": "2026-07-13T09:30:00+00:00",
                "employmentType": "Contract",
                "jobUrl": "https://jobs.ashbyhq.com/example/abc-123",
                "compensation": {
                    "compensationTierSummary": "USD 20-30 hourly",
                    "summaryComponents": [
                        {
                            "compensationType": "Salary",
                            "interval": "1 HOUR",
                            "currencyCode": "USD",
                            "minValue": 20,
                            "maxValue": 30,
                        }
                    ],
                },
            }
        ],
    }
    client, http = make_http(payload)
    async with client:
        jobs = [job async for job in AshbyCollector("example-company", http).collect()]

    assert len(jobs[0].external_job_id) == 32
    assert jobs[0].employment_type == EmploymentType.CONTRACT
    assert jobs[0].location_type == LocationType.ONSITE
    assert jobs[0].compensation_currency == "USD"
    assert jobs[0].compensation_period == "hour"
