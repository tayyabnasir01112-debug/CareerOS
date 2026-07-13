# CareerOS architecture

CareerOS is a modular, service-oriented FastAPI application. Components are named for their
responsibilities; the current collection and filtering services are deterministic software
services, not autonomous AI agents.

## Collection and normalization

Greenhouse, Lever, and Ashby adapters implement the shared async collector interface. Each adapter
uses documented public job-board endpoints through a bounded HTTP client with an identifying
User-Agent, timeouts, limited exponential retries, a response-size ceiling, disabled redirects,
and conservative connections. Source identifiers are validated slugs rather than arbitrary URLs.

Collectors convert ATS-specific fields into the `CollectedJob` contract. HTML cleanup removes
active or tracking-capable elements while preserving meaningful headings, lists, requirements, and
compensation text. Public source payloads are retained for traceability after recursively removing
header-, cookie-, and authorization-shaped fields.

## Deduplication and eligibility

The collection service orchestrates each configured board or site independently. Database
uniqueness protects `(source, external_job_id)`. New records also receive a deterministic SHA-256
fingerprint made from normalized title, company, and location, allowing cross-source duplicates to
be skipped. Material changes update an existing source record; unchanged records only refresh the
latest collection timestamp.

Rule-based eligibility runs after insertion or material updates. Hard exclusions such as unpaid,
commission-only, frontend-only, stale, or citizenship-restricted listings are rejected. Missing or
incomparable compensation and publication data are flagged rather than presented as known facts.

## Persistence and interfaces

Async SQLAlchemy repositories persist companies, jobs, evaluations, application-package metadata,
and `CollectorRun` audit records. SQLite is the local database, timestamps round-trip as UTC, and
Alembic owns schema evolution. The database boundary can later support a server database without
moving business rules into route handlers.

FastAPI routes delegate to query and collection services. The Windows-compatible CLI calls the same
collection service, so API and CLI behavior share normalization, filtering, error isolation, and
statistics. No background scheduler is active.

## Future AI evaluation boundary

A later evaluation service may read verified candidate configuration and eligible stored jobs, then
call the OpenAI API using versioned prompts and structured outputs. It must never invent candidate
experience, mutate collection rules, or hide model provenance. OpenAI calls, company research,
application generation, Discord delivery, scheduling, analytics, and frontend work remain outside
the implemented release.
