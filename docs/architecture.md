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

`SourceRegistryValidator` maintains the discovery boundary separately from collection. Registry
entries are strict platform/identifier records, never arbitrary request URLs. Validation maps each
entry to one fixed public ATS endpoint, rejects redirects and authentication, verifies the expected
JSON shape, records active-job state and UTC timestamps, and applies a seven-day TTL/cooldown.
`sync_source_config` generates the runtime board lists from enabled valid entries while retaining
the existing conservative collection settings.

## Deduplication and eligibility

The collection service orchestrates each configured board or site independently. Database
uniqueness protects `(source, external_job_id)`. New records also receive a deterministic SHA-256
fingerprint made from normalized title, company, and location, allowing cross-source duplicates to
be skipped. Material changes update an existing source record; unchanged records only refresh the
latest collection timestamp.

Rule-based eligibility runs after every observed source record. `LocationEligibilityService`
persists an explicit classification and evidence independently of candidate willingness to
relocate. Country-restricted remote jobs and unsupported foreign onsite/hybrid jobs are rejected;
unclear locations remain review-only and cannot reach automatic notification. Hard exclusions such as unpaid,
commission-only, frontend-only, stale, or citizenship-restricted listings are rejected. Missing or
incomparable compensation and publication data are flagged rather than presented as known facts.

`EvaluationPriorityService` stores a deterministic pre-score from target-title match, verified
skill overlap, confirmed location, recency, employment compatibility, compensation, and description
completeness. The evaluation repository excludes location failures and weak candidates before its
five-job budget, prioritizes confirmed remote work, and prefers never-evaluated backlog records.

## Persistence and interfaces

Async SQLAlchemy repositories persist companies, jobs, evaluations, application-package metadata,
and `CollectorRun` audit records. SQLite is the local database, timestamps round-trip as UTC, and
Alembic owns schema evolution. The database boundary can later support a server database without
moving business rules into route handlers.

FastAPI routes delegate to query and collection services. Windows-compatible CLIs call the same
services, so API, manual pipeline, and scheduled pipeline behavior share normalization, filtering,
error isolation, and statistics.

## AI evaluation boundary

The implemented recruiter evaluation boundary has four explicit services:

- `EvaluationInputBuilder` creates sanitized, size-bounded prompts and deterministic component
  fingerprints from normalized jobs, verified configuration, eligibility, and versioned prompt
  files. Raw collector payloads never cross this boundary.
- `RecruiterEvaluator` owns limited transient retries plus one concise schema-repair attempt for an
  invalid structured result and delegates prepared input to the injected provider interface.
- `OpenAIRecruiterEvaluationProvider` uses the async Responses API with Pydantic Structured Outputs,
  no tools, no streaming, and provider-side storage disabled. Tests inject
  `FakeRecruiterEvaluationProvider` and never contact OpenAI.
- `EvaluationRepository` and `EvaluationOrchestrator` own persistence, successful-result caching,
  UTC daily and per-run budgets, deterministic selection, failure isolation, and token summaries.

Cache identity combines job content, candidate profile, job preferences, prompt content/version,
and configured model. Failed calls remain retryable; deterministic ineligibility spends no API
request. Authentication, permission, and quota failures stop a batch because further calls cannot
meaningfully succeed. The default concurrency is intentionally one.

Versioned prompts prohibit invented experience, protected-characteristic decisions, unsupported
hiring-likelihood claims, hidden reasoning disclosure, and instructions embedded in job data. Only
the validated user-facing result and minimal API metadata are persisted. Validation failures retain
only sanitized field paths and error types, never the provider response body.

## Notification and local scheduling boundary

`CareerPipelineOrchestrator` composes collection and evaluation, then passes qualifying successful
results to `DiscordNotificationService`. Its policy rechecks deterministic eligibility and confirmed
location, score, recommendation, and notification fingerprint; AI output cannot override a location
rejection. `JobNotificationFormatter` creates one bounded embed per
job. `NotificationRepository` persists attempts and a unique evaluation fingerprint: successful
fingerprints are skipped while failed deliveries remain retryable. `DiscordWebhookProvider` is the
only component that receives the webhook URL and uses bounded async HTTP without redirects. Tests
inject `FakeNotificationProvider` and block external traffic.

The explicit Windows Task Scheduler scripts launch the same CLI every three hours without keeping
FastAPI running. Task definitions contain project paths but no credentials; ignored `.env` settings
are loaded at process startup. `StartWhenAvailable`, `WakeToRun`, and `IgnoreNew` cover missed starts,
wake behavior, and overlap prevention.

Company research, resume changes, application generation, analytics, automatic submission, and
frontend work remain outside the implemented release.
