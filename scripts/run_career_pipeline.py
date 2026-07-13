import argparse
import asyncio

from app.core.config import load_settings
from app.db.session import Database
from app.schemas.notification import CareerPipelineSummary, PipelineRunOptions
from app.services.career_pipeline import run_career_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the complete CareerOS job pipeline")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--source", choices=("greenhouse", "lever", "ashby"))
    source.add_argument("--all", action="store_true", help="Run all enabled collectors")
    parser.add_argument("--limit", type=int, help="Maximum jobs to consider for evaluation")
    parser.add_argument("--dry-run", action="store_true", help="Never call OpenAI or Discord")
    parser.add_argument("--no-notify", action="store_true", help="Do not send Discord messages")
    parser.add_argument(
        "--force-evaluation", action="store_true", help="Ignore successful evaluation cache"
    )
    return parser.parse_args()


async def run(options: PipelineRunOptions) -> tuple[int, CareerPipelineSummary]:
    settings = load_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            summary = await run_career_pipeline(session, settings, options)
    finally:
        await database.dispose()
    print(summary.model_dump_json(indent=2))
    return (0 if summary.jobs_fetched or not summary.errors else 1), summary


def main() -> None:
    args = parse_args()
    options = PipelineRunOptions(
        source=args.source,
        all_sources=args.all,
        limit=args.limit,
        dry_run=args.dry_run,
        no_notify=args.no_notify,
        force_evaluation=args.force_evaluation,
    )
    exit_code, _ = asyncio.run(run(options))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
