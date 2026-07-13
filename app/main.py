import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.core.config import Settings, load_settings
from app.core.logging import configure_logging
from app.db.session import Database
from app.services.configuration import (
    load_candidate_profile,
    load_job_preferences,
    load_source_config,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or load_settings()
    configure_logging(application_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(application_settings.database_url)
        app.state.settings = application_settings
        app.state.database = database
        try:
            load_candidate_profile(application_settings)
            load_job_preferences(application_settings)
            load_source_config(application_settings)
            logging.getLogger(__name__).info("CareerOS configuration validated")
            yield
        finally:
            await database.dispose()

    application = FastAPI(title=application_settings.app_name, lifespan=lifespan)
    application.include_router(router)
    return application
