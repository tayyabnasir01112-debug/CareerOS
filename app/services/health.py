from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class HealthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def database_is_ready(self) -> bool:
        try:
            await self.session.execute(text("SELECT 1 FROM jobs LIMIT 1"))
        except Exception:
            return False
        return True
