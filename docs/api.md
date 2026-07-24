# CareerOS API Usage

The API is defined in `app/api/routes.py`. Examples below use only implemented routes.

Start the app:

```powershell
python -m uvicorn app.main:create_app --factory --reload
```

## GET /health

Purpose: verify that the API is running and the database schema is ready.

curl:

```bash
curl http://127.0.0.1:8000/health
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/health"
```

Example response:

```json
{
  "status": "ok",
  "database": "ready"
}
```

Common error:

```json
{
  "detail": "Database is unavailable. Run `python -m scripts.init_db` first."
}
```

## GET /jobs

Purpose: list normalized jobs.

curl:

```bash
curl "http://127.0.0.1:8000/jobs?limit=10&offset=0"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs?limit=10&offset=0"
```

Example response:

```json
{
  "items": [],
  "total": 0,
  "limit": 10,
  "offset": 0
}
```

Common error: `422 Unprocessable Entity` when `limit` is outside `1..200` or `offset` is negative.

## GET /jobs/{job_id}

Purpose: read one normalized job.

curl:

```bash
curl http://127.0.0.1:8000/jobs/1
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/jobs/1"
```

Common error:

```json
{
  "detail": "Job not found"
}
```

## GET /runs

Purpose: list collector run audit records.

curl:

```bash
curl "http://127.0.0.1:8000/runs?limit=10&offset=0"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/runs?limit=10&offset=0"
```

Example response:

```json
{
  "items": [],
  "total": 0,
  "limit": 10,
  "offset": 0
}
```

## POST /runs/collect

Purpose: collect jobs from configured public ATS sources.

Request body: none. Optional query parameter: `source=greenhouse`, `source=lever`, or `source=ashby`.

curl:

```bash
curl -X POST "http://127.0.0.1:8000/runs/collect?source=greenhouse"
```

PowerShell:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/runs/collect?source=greenhouse"
```

Example response: see `examples/collection-response.json`.

Common error: `422 Unprocessable Entity` when `source` is not one of the supported collector platforms.

## POST /evaluations/run

Purpose: evaluate eligible jobs or run a safe dry-run input preparation flow.

Request body:

```json
{
  "job_id": null,
  "limit": 5,
  "minimum_rule_score": 75,
  "force": false,
  "dry_run": true
}
```

curl:

```bash
curl -X POST http://127.0.0.1:8000/evaluations/run \
  -H "Content-Type: application/json" \
  -d "{\"limit\":5,\"minimum_rule_score\":75,\"force\":false,\"dry_run\":true}"
```

PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/evaluations/run" `
  -ContentType "application/json" `
  -Body '{"limit":5,"minimum_rule_score":75,"force":false,"dry_run":true}'
```

Example response: see `examples/evaluation-response.json`.

Common errors:

- `422 Unprocessable Entity` when `limit` is outside `1..100`.
- `configuration_error` in the response body when a live run is requested without OpenAI configuration.

## GET /evaluations

Purpose: list persisted evaluations.

curl:

```bash
curl "http://127.0.0.1:8000/evaluations?limit=10&offset=0"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/evaluations?limit=10&offset=0"
```

Example response:

```json
{
  "items": [],
  "total": 0,
  "limit": 10,
  "offset": 0
}
```

## GET /evaluations/{evaluation_id}

Purpose: read one persisted evaluation.

Common error:

```json
{
  "detail": "Evaluation not found"
}
```

## GET /jobs/{job_id}/evaluation

Purpose: read the latest evaluation for a job.

Common error:

```json
{
  "detail": "No evaluation found for this job"
}
```

## POST /pipeline/run

Purpose: run collection, evaluation, and notification orchestration through one endpoint.

Request body:

```json
{
  "source": "greenhouse",
  "all_sources": false,
  "limit": 5,
  "dry_run": true,
  "no_notify": true,
  "force_evaluation": false
}
```

curl:

```bash
curl -X POST http://127.0.0.1:8000/pipeline/run \
  -H "Content-Type: application/json" \
  -d "{\"source\":\"greenhouse\",\"limit\":5,\"dry_run\":true,\"no_notify\":true}"
```

PowerShell:

```powershell
Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/pipeline/run" `
  -ContentType "application/json" `
  -Body '{"source":"greenhouse","limit":5,"dry_run":true,"no_notify":true}'
```

Common errors:

- `422 Unprocessable Entity` when both `source` and `all_sources` are provided.
- Configuration errors are returned inside the summary when optional providers are disabled or missing.

## GET /notifications

Purpose: list persisted notification attempts.

curl:

```bash
curl "http://127.0.0.1:8000/notifications?limit=10&offset=0"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/notifications?limit=10&offset=0"
```

Example response:

```json
{
  "items": [],
  "total": 0,
  "limit": 10,
  "offset": 0
}
```

## GET /notifications/{notification_id}

Purpose: read one persisted notification attempt.

Common error:

```json
{
  "detail": "Notification not found"
}
```
