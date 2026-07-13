# CareerOS

CareerOS is a production-style AI career platform that discovers public job listings, normalizes
and deduplicates opportunities, evaluates rule-based eligibility, and will later prepare tailored
application packages. The current release is a tested backend and public collection foundation;
planned AI and application-writing capabilities are not yet implemented.

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
- Mocked testing, strict static analysis, secret scanning, and GitHub Actions CI

Planned:

- OpenAI recruiter evaluation using the verified candidate profile
- Attributable company research
- Resume optimization
- Tailored application writing and preparation packages
- Discord notifications
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
6. A future AI evaluation service will consume only verified profiles and eligible stored jobs; it
   is deliberately outside the current collection pipeline.

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
The `OPENAI_API_KEY` and `DISCORD_WEBHOOK_URL` names in `.env.example` are reserved for later work
and are not read or used by the current application.

## Public collector configuration

Collectors are opt-in in `config/source_config.yaml`; all tracked examples are disabled. Replace
`example-company` with a real public board identifier, then set only the platform you want to use
to `enabled: true`.

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

The shared collection settings control the identifying User-Agent, timeout, limited retry count,
exponential-backoff base, and a conservative connection limit. Invalid or disabled identifiers do
not silently produce successful runs.

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
- CareerOS does not discover board identifiers automatically. Configure only organizations whose
  public careers pages you intentionally want to research.
- ATS fields vary. Missing publication time, workplace type, employment type, or compensation is
  preserved as unknown and handled conservatively; undisclosed compensation is flagged.
- Greenhouse custom metadata is not standardized, and Lever does not provide a general updated-at
  field. Ashby compensation can contain multiple geographic tiers; the collector preserves the full
  raw payload and uses only its public summary component for normalized numeric fields.
- Collection is manual in this phase. No background scheduler is enabled.

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
