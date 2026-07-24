# CareerOS Local Demo

This demo shows CareerOS running locally without exposing credentials. The safe path uses dry-run evaluation and disabled notifications, so no OpenAI or Discord call is required.

## Demo Goal

Show a reviewer that CareerOS has a real backend workflow:

1. Start the FastAPI app.
2. Verify the database is ready.
3. Trigger a safe evaluation dry run.
4. Inspect API-shaped responses.
5. Explain how collection, evaluation, persistence, and notification boundaries fit together.

## Prerequisites

- Python 3.12
- PowerShell
- Git
- Optional: Docker, if you want to build the API image

## Local Setup

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m scripts.init_db
```

## Sample Environment Configuration

Keep secrets blank for the safe demo:

```dotenv
CAREEROS_ENVIRONMENT=development
CAREEROS_DATABASE_URL=sqlite+aiosqlite:///./data/careeros.db
OPENAI_API_KEY=
OPENAI_RECRUITER_MODEL=
DISCORD_WEBHOOK_URL=
DISCORD_NOTIFICATIONS_ENABLED=false
```

Set `OPENAI_RECRUITER_MODEL` only when running live OpenAI evaluation with a model available to your OpenAI project.

## Start the API

```powershell
python -m uvicorn app.main:create_app --factory --reload
```

Open:

- API docs: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

## Example Collection Request

Collection uses public ATS endpoints and may make external network requests. For a live local run:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/runs/collect?source=greenhouse"
```

Example request/response shapes are in:

- `examples/collection-request.json`
- `examples/collection-response.json`

## Example Matching/Evaluation Request

Safe dry run:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/evaluations/run" `
  -ContentType "application/json" `
  -Body '{"dry_run":true,"limit":5}'
```

The dry run selects eligible jobs, sanitizes inputs, and returns deterministic input fingerprints. It does not call OpenAI and does not persist successful evaluations.

Example request/response shapes are in:

- `examples/evaluation-request.json`
- `examples/evaluation-response.json`

## Example Notification Output

Notifications require a Discord webhook only for live delivery. The formatter and provider boundary are tested with fake providers, and a sanitized preview is available in:

- `examples/notification-preview.json`

For safe local pipeline testing without notifications:

```powershell
python -m scripts.run_career_pipeline --all --dry-run
python -m scripts.run_career_pipeline --all --no-notify
```

## Sanitized Logs

Example structured logs are in:

- `examples/sample-logs.txt`

Logs and error messages are redacted through `app/core/security.py`.

## Expected Failure Example

If OpenAI evaluation is requested without an API key or configured model, CareerOS returns a configuration error instead of attempting a provider call.

Example response:

```json
{
  "jobs_considered": 0,
  "evaluations_requested": 0,
  "evaluations_completed": 0,
  "cached_evaluations_reused": 0,
  "skipped_by_deterministic_eligibility": 0,
  "skipped_by_score_or_status_rules": 0,
  "failed_evaluations": 0,
  "daily_budget_remaining": 25,
  "total_input_tokens": 0,
  "total_output_tokens": 0,
  "errors": ["configuration_error: OPENAI_API_KEY is not configured"],
  "dry_run_inputs": []
}
```

## Reset and Cleanup

```powershell
Stop-Process -Name uvicorn -ErrorAction SilentlyContinue
Remove-Item .\data\careeros.db -ErrorAction SilentlyContinue
python -m scripts.init_db
```

If you created a local `.env` with real secrets, do not commit it. Rotate any credential that was accidentally printed, logged, or committed.

## 60-90 Second Loom Script

1. "This is CareerOS, a Python backend project for collecting public job listings, normalizing them, evaluating fit against verified candidate evidence, and preparing safe notifications."
2. "The README starts with the problem, implemented capabilities, architecture diagram, and quick start. The project separates API routes, services, collectors, schemas, persistence, and provider boundaries."
3. "In the API docs, I can run safe local endpoints without credentials. The dry-run evaluation path validates the workflow without calling OpenAI."
4. "The database is managed with async SQLAlchemy and Alembic migrations. Tests use fake OpenAI and Discord providers, and unmocked network calls are blocked."
5. "The examples directory shows sanitized request and response shapes, notification preview data, and structured logs."
6. "The quality commands run secret scanning, Ruff, strict Mypy, database initialization, Pytest, and optional coverage/dependency audit checks."
7. "The roadmap is clearly separated from implemented functionality, so reviewers can see what works today and what is intentionally future work."
