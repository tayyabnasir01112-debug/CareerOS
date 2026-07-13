from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import make_url

from app.core.config import load_settings


def main() -> None:
    settings = load_settings()
    database_path = make_url(settings.database_url).database
    if database_path and database_path != ":memory:":
        Path(database_path).expanduser().parent.mkdir(parents=True, exist_ok=True)

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
    print("CareerOS database initialized successfully.")


if __name__ == "__main__":
    main()
