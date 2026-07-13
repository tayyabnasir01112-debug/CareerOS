import argparse
import asyncio

import httpx

from app.core.config import load_settings
from app.schemas.configuration import RegistryPlatform
from app.services.configuration import load_source_registry
from app.services.source_registry import SourceRegistryValidator, write_yaml_model


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate public ATS source registry entries")
    parser.add_argument("--platform", choices=tuple(item.value for item in RegistryPlatform))
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore validation TTLs and cooldowns and check every selected source",
    )
    parser.add_argument(
        "--prune-invalid",
        action="store_true",
        help="Remove currently invalid candidates after validation",
    )
    return parser.parse_args()


async def run(
    platform: RegistryPlatform | None, *, refresh: bool, prune_invalid: bool = False
) -> int:
    settings = load_settings()
    registry = load_source_registry(settings)
    limits = httpx.Limits(max_connections=3, max_keepalive_connections=3)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20),
        follow_redirects=False,
        limits=limits,
        headers={
            "User-Agent": "CareerOS/0.4 personal-job-research (+https://tayyabautomates.com)",
            "Accept": "application/json",
        },
    ) as client:
        summary = await SourceRegistryValidator(client, max_concurrency=3).validate(
            registry,
            platform=platform,
            refresh=refresh,
        )
    if prune_invalid:
        registry.sources = [
            source for source in registry.sources if source.validation_status.value != "invalid"
        ]
    write_yaml_model(settings.source_registry_path, registry)
    print(summary.model_dump_json(indent=2))
    return 0 if summary.valid_boards else 1


def main() -> None:
    args = parse_args()
    platform = RegistryPlatform(args.platform) if args.platform else None
    if platform is not None and args.prune_invalid:
        raise SystemExit("--prune-invalid cannot be combined with --platform")
    raise SystemExit(
        asyncio.run(run(platform, refresh=args.refresh, prune_invalid=args.prune_invalid))
    )


if __name__ == "__main__":
    main()
