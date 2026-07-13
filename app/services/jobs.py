from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import CollectorRun, Job


class JobQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_jobs(self, *, limit: int, offset: int) -> tuple[list[Job], int]:
        statement = (
            select(Job)
            .options(selectinload(Job.company))
            .order_by(Job.discovered_at.desc(), Job.id.desc())
            .limit(limit)
            .offset(offset)
        )
        jobs = list((await self.session.scalars(statement)).all())
        total = await self.session.scalar(select(func.count()).select_from(Job))
        return jobs, total or 0

    async def get_job(self, job_id: int) -> Job | None:
        statement = select(Job).options(selectinload(Job.company)).where(Job.id == job_id)
        return cast(Job | None, await self.session.scalar(statement))


class CollectorRunQueryService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_runs(self, *, limit: int, offset: int) -> tuple[list[CollectorRun], int]:
        statement = (
            select(CollectorRun)
            .order_by(CollectorRun.started_at.desc(), CollectorRun.id.desc())
            .limit(limit)
            .offset(offset)
        )
        runs = list((await self.session.scalars(statement)).all())
        total = await self.session.scalar(select(func.count()).select_from(CollectorRun))
        return runs, total or 0
