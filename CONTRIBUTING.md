# Contributing to CareerOS

Thank you for considering a contribution. CareerOS favors small, reviewable changes that preserve
its Windows-first, service-oriented architecture and ethical public-data boundaries.

## Development setup

Use Python 3.12 and follow the native Windows setup in the [README](README.md). Docker must not be a
requirement for local development, tests, migrations, or collection.

Before opening a pull request, run:

```powershell
python -m scripts.scan_secrets
python -m ruff format .
python -m ruff check .
python -m mypy app scripts tests
python -m pytest
```

## Design expectations

- Keep HTTP and database operations asynchronous.
- Keep route handlers thin and place business rules in services.
- Add Alembic migrations for schema changes.
- Use documented public endpoints; never bypass authentication, CAPTCHA, access controls, or rate
  limits.
- Mock all external HTTP traffic in tests.
- Inject a fake recruiter provider in tests; no test or CI job may contact the live OpenAI API.
- Never invent candidate facts or commit credentials, resumes, databases, generated applications,
  logs, or private job data.
- Preserve typed functions, strict Mypy compatibility, deterministic behavior, and UTC timestamps.

Open an issue before a large architectural change. Security concerns should follow
[SECURITY.md](SECURITY.md), not a public issue.
