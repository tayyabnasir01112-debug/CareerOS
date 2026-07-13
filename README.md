# CareerOS

CareerOS is a production-style AI career platform that discovers public job listings, normalizes
and deduplicates opportunities, evaluates them against verified candidate evidence, and sends
useful matches to Discord. Tailored application packages remain a future, human-reviewed phase.

CareerOS is owned and maintained by [Tayyab Nasir](https://github.com/tayyabnasir01112-debug).
Portfolio links are available at [tayyabautomates.com](https://tayyabautomates.com) and
[LinkedIn](https://www.linkedin.com/in/tayyabautomates).

## Project status

Implemented now:

- FastAPI backend and structured JSON logging
- Async SQLAlchemy persistence, local SQLite, and Alembic migrations
- Public Greenhouse, Lever, and Ashby collectors
- HTML and source-field normalization
- Source-level and cross-source deterministic deduplication
- Rule-based eligibility filtering
- CLI and API collection with partial-failure statistics
- Verified recruiter-style OpenAI evaluation with structured outputs, caching, and strict budgets
- Deduplicated Discord notifications and an end-to-end career pipeline
- Optional local automation through Windows Task Scheduler
- Mocked testing, strict static analysis, secret scanning, and GitHub Actions CI

Planned:

- Attributable company research
- Resume optimization
- Tailored application writing and preparation packages
- Career analytics dashboard and frontend

See the [roadmap](ROADMAP.md) for milestone boundaries and sequencing.

## Architecture overview

CareerOS uses service-oriented internal boundaries:

1. Collector adapters read documented public ATS feeds with bounded async HTTP behavior.
2. Normalization converts platform fields and HTML descriptions into a shared job contract.
3. The collection service applies source uniqueness, deterministic cross-source fingerprints, and
   rule-based eligibility decisions.
4. SQLAlchemy services persist companies, jobs, evaluations, packages, and collector-run audit
   records in SQLite for local use.
5. FastAPI routes and the PowerShell-compatible CLI call the same business services.
6. The recruiter evaluation service sends only sanitized normalized job data and verified profile
   facts to the configured OpenAI model, then validates and persists structured output.
7. The notification service formats qualifying evaluations as bounded Discord embeds and records a
   delivery fingerprint so reruns cannot send the same result twice.

More detail is available in [docs/architecture.md](docs/architecture.md).

## Requirements

- Windows 10 or 11
- Python 3.12 available through the `py` launcher
- PowerShell 5.1 or PowerShell 7+
- No Docker or external database is required

## Windows PowerShell setup

Run these commands from the repository root:

```powershell
py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m scripts.init_db
python -m uvicorn app.main:create_app --factory --reload
```

Open `http://127.0.0.1:8000/docs` for the API documentation. Collection can also be triggered with
`POST /runs/collect` and the optional `source` query parameter.

All `CAREEROS_*` settings can be changed in `.env` or as process environment variables. Candidate
facts and job preferences live in validated YAML files under `config/`. Missing or malformed files
produce an actionable startup error. Do not put secrets or private resume details in tracked YAML.
`OPENAI_API_KEY` configures recruiter evaluation, while `DISCORD_WEBHOOK_URL` remains reserved and
unused. The OpenAI key is read only when a non-dry recruiter evaluation runs.

## Recruiter evaluation

CareerOS evaluates eligible or review-flagged jobs against the verified YAML profile through the
OpenAI Responses API and Pydantic Structured Outputs. The configured default is `gpt-5.4-mini`; set
`OPENAI_RECRUITER_MODEL` to another Structured-Outputs-capable model available to your OpenAI
project. Model names live in configuration, not business logic.

Create the local environment file if needed, then edit it without printing the key in terminal
history:

```powershell
Copy-Item .env.example .env -ErrorAction SilentlyContinue
notepad .env
python -m scripts.init_db
```

Set these entries in `.env`:

```dotenv
OPENAI_API_KEY=
OPENAI_RECRUITER_MODEL=gpt-5.4-mini
OPENAI_MAX_EVALUATIONS_PER_RUN=10
OPENAI_MAX_EVALUATIONS_PER_DAY=25
OPENAI_MAX_INPUT_CHARACTERS=18000
OPENAI_REQUEST_TIMEOUT_SECONDS=45
```

Leave `OPENAI_API_KEY` blank until you intentionally run a live evaluation. Start with an offline
dry run, which performs selection, sanitization, truncation, and fingerprinting but makes no OpenAI
call and creates no successful evaluation record:

```powershell
python -m scripts.evaluate_jobs --dry-run --limit 5
```

Evaluate one controlled job or a bounded batch:

```powershell
python -m scripts.evaluate_jobs --job-id 123 --limit 1
python -m scripts.evaluate_jobs --limit 5
python -m scripts.evaluate_jobs --minimum-rule-score 75
python -m scripts.evaluate_jobs --job-id 123 --force
```

The API equivalents are `POST /evaluations/run`, `GET /evaluations`,
`GET /evaluations/{evaluation_id}`, and `GET /jobs/{job_id}/evaluation`. API callers may select a
job, limit, force mode, and dry-run mode, but cannot override credentials, model, prompt files, or
budgets.

Successful cache reuse requires unchanged job content, candidate profile, preferences, prompt
content/version, and model. Failed evaluations can be retried; `--force` intentionally bypasses a
successful cache entry. API attempts—including failures—count against the UTC daily budget. Cached,
dry-run, and deterministic-ineligible outcomes do not spend that budget. Summaries report token
usage but never estimate price from hardcoded rates.

### Information sent to OpenAI

- Normalized title, company, location, workplace and employment type
- Sanitized description, compensation, and public listing dates
- Verified facts from `candidate_profile.yaml`
- Job preferences and deterministic eligibility reasons
- Verified achievements and public professional portfolio links

CareerOS never sends raw collector payloads, request headers, cookies, API keys, local paths, phone
numbers, resumes, generated applications, or unrelated personal information. It does not request
tools, web search, file search, code execution, computer use, or hidden reasoning. It stores only
the validated evaluation plus minimal response ID, token counts, duration, cache fingerprints, and
sanitized errors—not full OpenAI responses or chain-of-thought.

### Evaluation troubleshooting

- `configuration_error`: add the key to the ignored `.env` file and confirm the model setting.
- `authentication_error` or `permission_error`: rotate or correct the key and verify model access.
- `quota_error`: resolve project billing or quota; CareerOS does not retry quota exhaustion.
- `rate_limit_error`, `timeout_error`, or `transient_provider_error`: transient calls use limited
  exponential retries with jitter, then persist a safe retryable failure.
- `invalid_structured_output`: retry the failed job; the malformed provider body is never stored.
- No jobs considered: collect jobs, apply migrations, and confirm listing age and rule eligibility.

Current limitations: listing expiry is enforced only where normalized date data exists; the
candidate YAML currently contains verified achievements but no individually verified portfolio
project catalog, so project recommendations remain empty; evaluation concurrency is deliberately
one request at a time.

## Discord notifications and full pipeline

Create a webhook in Discord under **Server Settings → Integrations → Webhooks**, choose the target
channel, and copy its URL. Place it only in the ignored local `.env` file:

```dotenv
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your-id/your-token
DISCORD_NOTIFICATIONS_ENABLED=true
DISCORD_MINIMUM_MATCH_SCORE=75
DISCORD_MAX_NOTIFICATIONS_PER_RUN=5
DISCORD_REQUEST_TIMEOUT_SECONDS=20
```

Run every enabled source, one source, a safe dry run, or a no-notification test:

```powershell
python -m scripts.run_career_pipeline --all
python -m scripts.run_career_pipeline --source greenhouse --limit 5
python -m scripts.run_career_pipeline --all --dry-run
python -m scripts.run_career_pipeline --all --no-notify
```

Dry runs never call OpenAI or Discord. `--no-notify` still permits collection and evaluation but
does not deliver messages. A Discord notification is eligible only for a successful evaluation at
or above the configured score with `strong_apply`, `apply`, or `consider`. CareerOS hashes the
evaluation input, structured result, prompt version, and model, then stores that fingerprint with
the delivery record. A sent fingerprint is never sent again; failed records remain retryable.

Discord receives only the job title, company, location, source/date, public URL, concise structured
match fields, skills, gaps, concern, positioning, and application-preparation flag. CareerOS never
sends raw descriptions or collector payloads, prompts, full OpenAI responses, webhook/API secrets,
phone numbers, local paths, or hidden reasoning.

An HTTP 404 usually means the webhook was deleted; create a replacement and update `.env`. HTTP
401/403 means Discord rejected the webhook credentials. HTTP 429 is retried using Discord's
`Retry-After` guidance, while persistent rate limits are reported without exposing response bodies.

### Windows Task Scheduler

Registration is always explicit. From the project root, register or remove the default three-hour
task with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\register_windows_task.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\unregister_windows_task.ps1
```

Use `-IntervalHours 6` to choose another interval. The task uses the project's
`.venv\Scripts\python.exe`, sets the project as its working directory, reads secrets from the local
`.env`, runs with a hidden PowerShell window, prevents overlapping instances, and writes only the
pipeline's sanitized JSON summary to `careeros-pipeline.log`.

For manual Task Scheduler setup, create a repeating task with program `powershell.exe`, start in the
CareerOS directory, and use arguments equivalent to:

```text
-NoProfile -NonInteractive -WindowStyle Hidden -Command "Set-Location 'C:\path\to\CareerOS'; & '.\.venv\Scripts\python.exe' -m scripts.run_career_pipeline --all"
```

Do not put webhook URLs or OpenAI keys in task arguments.

## Public collector configuration

`config/source_registry.yaml` is the maintainable source catalog. It records company display name,
ATS platform and identifier, canonical public careers URL, categories, remote relevance, enabled
state, active-job state, validation status, UTC validation time, and failure cooldown metadata.
The committed registry contains 97 live-validated boards; the generated runtime subset enables 88
active, remote-relevant boards: 37 Greenhouse, 23 Lever, and 28 Ashby.

```yaml
greenhouse:
  enabled: true
  boards:
    - company-board-token
lever:
  enabled: false
  sites:
    - company-site-name
ashby:
  enabled: false
  boards:
    - company-jobs-page-name
```

- Greenhouse uses its unauthenticated Job Board API with `content=true`. The board token is the
  segment after `boards.greenhouse.io/` or `job-boards.greenhouse.io/`, and is documented in the
  [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html).
- Lever uses its public v0 Postings API in JSON mode. The site name is the segment after
  `jobs.lever.co/`; see the [Lever Postings API](https://github.com/lever/postings-api).
- Ashby uses its public Job Postings API with compensation enabled. The jobs page name is the final
  segment of `jobs.ashbyhq.com/{name}`; see the
  [Ashby public job postings guide](https://developers.ashbyhq.com/docs/public-job-posting-api).

Validate the registry or one platform, explicitly force a refresh, then regenerate runtime config:

```powershell
python -m scripts.validate_sources
python -m scripts.validate_sources --platform greenhouse
python -m scripts.validate_sources --refresh
python -m scripts.sync_source_config
```

Normal validation honors a seven-day validation TTL and invalid-source cooldown; `--refresh`
explicitly rechecks the selected sources. Validation uses fixed public ATS endpoint templates,
bounded async HTTP, no redirects, and no authentication. Invalid or protected candidates are
disabled and never synced. `sync_source_config` preserves the shared collection settings while
generating only enabled, currently valid identifiers. Use `--prune-invalid` after reviewing a
discovery batch if invalid audit entries should be removed from the registry.

The shared collection settings control the identifying User-Agent, timeout, limited retry count,
exponential-backoff base, and a conservative connection limit. A failure from one board is recorded
without stopping other configured boards.

## Running collectors from PowerShell

Initialize or migrate SQLite before collecting:

```powershell
cd C:\Users\ts199\CareerOS
.\.venv\Scripts\Activate.ps1
python -m scripts.init_db
python -m scripts.collect_jobs --source greenhouse
python -m scripts.collect_jobs --source lever
python -m scripts.collect_jobs --source ashby
python -m scripts.collect_jobs --all
```

`--source` runs the enabled identifiers for one platform. `--all` runs every enabled platform.
A partial failure returns an honest summary but remains successful if at least one requested board
or site completed meaningfully. If nothing matched or every requested execution failed, the CLI
returns a non-zero exit code.

The API equivalent is:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/runs/collect?source=greenhouse"
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/runs/collect"
```

## Normalization and deduplication

HTML descriptions are converted to readable text while headings, list items, requirements, and
compensation content are retained. Scripts, styles, forms, iframes, and excessive whitespace are
removed. Source URLs and original public payloads are stored for traceability.

Each `(source, external_job_id)` pair is database-protected. A repeated source record is updated
only when material normalized data changes. New jobs also receive a deterministic SHA-256
fingerprint from normalized title, company, and location; an existing cross-source fingerprint is
skipped. Rule-based eligibility runs for new and materially updated jobs, and each configured board
or site receives its own `CollectorRun` statistics record.

## Known limitations and boundaries

- Collectors read only documented public job-board data. They do not submit applications, access
  private ATS APIs, authenticate, scrape search engines, or bypass CAPTCHA, rate limits, robots,
  access controls, or other platform protections.
- CareerOS does not guess or crawl for identifiers at runtime. Registry additions must be sourced
  from a public careers page and pass `validate_sources` before sync.
- ATS fields vary. Missing publication time, workplace type, employment type, or compensation is
  preserved as unknown and handled conservatively; undisclosed compensation is flagged.
- Greenhouse custom metadata is not standardized, and Lever does not provide a general updated-at
  field. Ashby compensation can contain multiple geographic tiers; the collector preserves the full
  raw payload and uses only its public summary component for normalized numeric fields.
- A large enabled registry increases collection duration and public request volume. The defaults
  intentionally use concurrency two and per-board isolation; curate `enabled` flags as needs change.

## Quality checks

```powershell
.\.venv\Scripts\Activate.ps1
python -m scripts.scan_secrets
python -m ruff format --check .
python -m ruff check .
python -m mypy app scripts tests
python -m pytest
```

To apply future database migrations, run `python -m scripts.init_db` again. Local SQLite data is
stored at `data/careeros.db` by default.

## Future deployment image

The `Dockerfile` is provided only as a future deployment option. It is not part of setup, tests,
database initialization, or any local development workflow.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) for development expectations and [SECURITY.md](SECURITY.md)
for private vulnerability reporting. Never include candidate-private information or credentials in
issues, logs, fixtures, or commits. CareerOS collectors are limited to documented public endpoints
and do not bypass authentication, CAPTCHA, access controls, or platform protections.

CareerOS is available under the [MIT License](LICENSE).
