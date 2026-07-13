from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session, get_settings
from app.core.config import Settings
from app.schemas.models import JobRead, PaginatedJobs, PaginatedRuns
from app.schemas.pipeline import CollectionSummary, CollectorPlatform
from app.services.collection import collect_configured_jobs
from app.services.health import HealthService
from app.services.jobs import CollectorRunQueryService, JobQueryService

router = APIRouter()
SessionDependency = Annotated[AsyncSession, Depends(get_session)]
SettingsDependency = Annotated[Settings, Depends(get_settings)]


class HealthResponse(BaseModel):
    status: str
    database: str


@router.get("/health", response_model=HealthResponse)
async def health(session: SessionDependency) -> HealthResponse:
    if not await HealthService(session).database_is_ready():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable. Run `python -m scripts.init_db` first.",
        )
    return HealthResponse(status="ok", database="ready")


@router.get("/jobs", response_model=PaginatedJobs)
async def list_jobs(
    session: SessionDependency,
    settings: SettingsDependency,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedJobs:
    page_limit = limit or settings.api_page_size
    items, total = await JobQueryService(session).list_jobs(limit=page_limit, offset=offset)
    return PaginatedJobs(
        items=[JobRead.model_validate(item) for item in items],
        total=total,
        limit=page_limit,
        offset=offset,
    )


@router.get("/jobs/{job_id}", response_model=JobRead)
async def get_job(job_id: int, session: SessionDependency) -> JobRead:
    job = await JobQueryService(session).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JobRead.model_validate(job)


@router.get("/runs", response_model=PaginatedRuns)
async def list_runs(
    session: SessionDependency,
    settings: SettingsDependency,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginatedRuns:
    page_limit = limit or settings.api_page_size
    items, total = await CollectorRunQueryService(session).list_runs(
        limit=page_limit, offset=offset
    )
    return PaginatedRuns(items=items, total=total, limit=page_limit, offset=offset)


@router.post("/runs/collect", response_model=CollectionSummary)
async def collect_jobs(
    session: SessionDependency,
    settings: SettingsDependency,
    source: Annotated[CollectorPlatform | None, Query()] = None,
) -> CollectionSummary:
    return await collect_configured_jobs(session, settings, source=source)
