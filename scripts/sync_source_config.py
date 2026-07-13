from app.core.config import load_settings
from app.services.configuration import load_source_config, load_source_registry
from app.services.source_registry import build_source_config, write_yaml_model


def main() -> None:
    settings = load_settings()
    registry = load_source_registry(settings)
    existing = load_source_config(settings)
    generated = build_source_config(registry, existing.collection)
    write_yaml_model(settings.source_config_path, generated)
    print(
        "Synced runtime sources: "
        f"greenhouse={len(generated.greenhouse.boards)}, "
        f"lever={len(generated.lever.sites)}, "
        f"ashby={len(generated.ashby.boards)}"
    )


if __name__ == "__main__":
    main()
