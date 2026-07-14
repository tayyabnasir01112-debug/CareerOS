# Changelog

All notable changes to CareerOS will be documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project intends to use semantic
versioning once stable releases begin.

## [Unreleased]

### Added

- Persisted deterministic location eligibility/evidence and a verified-facts queue pre-score.
- Confirmed-location notification gating with configurable consider behavior and suppression counts.
- One-time concise structured-output repair with sanitized validation field diagnostics.
- Request-schema failures no longer consume a redundant repair call; optional verbosity is omitted
  for compatibility across configurable structured-output models.
- Task Scheduler wake, missed-run, and overlap-safe settings.

- Windows-first FastAPI backend with async SQLAlchemy, SQLite, and Alembic.
- Validated candidate, preference, and collector configuration.
- Public Greenhouse, Lever, and Ashby collectors with bounded HTTP behavior.
- HTML normalization, deterministic deduplication, and rule-based eligibility filtering.
- Collection CLI and API with per-source run statistics and partial-failure handling.
- Structured JSON logging, credential redaction, secret scanning, and mocked tests.
- GitHub Actions CI and public repository contribution templates.
- Recruiter-style OpenAI evaluation through the async Responses API and Structured Outputs.
- Versioned verified-evidence prompts, sanitized input preparation, and component fingerprints.
- Successful-evaluation caching, UTC daily/per-run budgets, token accounting, and safe retries.
- Evaluation CLI and paginated API endpoints with offline dry-run support.
- Additive structured evaluation persistence and fully mocked provider tests.
- Discord webhook delivery with bounded embeds, retries, rate-limit handling, and persisted
  notification fingerprints.
- End-to-end collection, eligibility, evaluation, and notification CLI/API orchestration.
- Optional three-hour Windows Task Scheduler registration and removal scripts.
- Curated public ATS source registry with fixed-endpoint validation, active-job metadata, UTC
  timestamps, validation TTLs, invalid-source cooldowns, and runtime configuration synchronization.
- Expanded runtime collection coverage across validated Greenhouse, Lever, and Ashby boards.

[Unreleased]: https://github.com/tayyabnasir01112-debug/CareerOS/commits/main
