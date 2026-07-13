# CareerOS roadmap

The roadmap describes intent, not shipped behavior. Priorities may change as the public collector
and data-quality foundation is exercised.

## Implemented

- FastAPI service, async SQLite persistence, and migrations
- Greenhouse, Lever, and Ashby public collectors
- Normalization, source and cross-source deduplication, and eligibility filtering
- Collection CLI and API
- Windows-native development, automated tests, secret scanning, and CI

## Next recommended milestone

- Verified OpenAI recruiter-style evaluation for eligible jobs
- Versioned prompts and structured evaluation output
- Strict daily evaluation budgets, retry controls, and auditable model metadata
- Tests that mock every OpenAI request and never invent candidate experience

## Later milestones

- Company research using attributable public sources
- Resume optimization and tailored application-package generation
- Application writing review workflow
- Discord notifications with explicit secret handling
- Scheduling and collection observability
- Career analytics dashboard and frontend
