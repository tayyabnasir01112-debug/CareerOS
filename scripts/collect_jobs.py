import argparse
import asyncio

from app.core.config import load_settings
from app.db.session import Database
from app.schemas.pipeline import CollectorPlatform
from app.services.collection import collect_configured_jobs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect public jobs into CareerOS")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--source", choices=("greenhouse", "lever", "ashby"), help="Run one enabled platform"
    )
    group.add_argument("--all", action="store_true", help="Run all enabled platforms")
    return parser.parse_args()


async def run(source: CollectorPlatform | None) -> int:
    settings = load_settings()
    database = Database(settings.database_url)
    try:
        async with database.session_factory() as session:
            summary = await collect_configured_jobs(session, settings, source=source)
    finally:
        await database.dispose()
    print(summary.model_dump_json(indent=2))
    return 0 if summary.sources_succeeded > 0 else 1


def main() -> None:
    args = parse_args()
    source: CollectorPlatform | None = args.source if not args.all else None
    raise SystemExit(asyncio.run(run(source)))


if __name__ == "__main__":
    main()
