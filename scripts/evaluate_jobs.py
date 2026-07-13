import argparse
import asyncio

from app.core.config import load_settings
from app.db.session import Database
from app.schemas.evaluation import EvaluationRunOptions, EvaluationRunSummary
from app.services.evaluation_orchestrator import run_configured_evaluations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate CareerOS jobs with recruiter criteria")
    parser.add_argument("--limit", type=int, help="Maximum jobs to consider")
    parser.add_argument("--job-id", type=int, help="Evaluate one stored job")
    parser.add_argument(
        "--minimum-rule-score",
        type=int,
        default=75,
        help="Minimum deterministic eligibility score (eligible=100, flagged=75)",
    )
    parser.add_argument("--force", action="store_true", help="Ignore successful cache entries")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Prepare sanitized inputs and fingerprints without API calls or writes",
    )
    return parser.parse_args()


async def run(options: EvaluationRunOptions) -> tuple[int, EvaluationRunSummary]:
    settings = load_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            summary = await run_configured_evaluations(session, settings, options)
    finally:
        await database.dispose()
    print(summary.model_dump_json(indent=2))
    meaningful = options.dry_run or summary.evaluations_completed > 0 or not summary.errors
    return (0 if meaningful else 1), summary


def main() -> None:
    args = parse_args()
    options = EvaluationRunOptions(
        job_id=args.job_id,
        limit=args.limit,
        minimum_rule_score=args.minimum_rule_score,
        force=args.force,
        dry_run=args.dry_run,
    )
    exit_code, _ = asyncio.run(run(options))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
