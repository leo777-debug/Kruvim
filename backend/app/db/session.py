from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_kwargs = {"pool_pre_ping": True}
if not settings.is_sqlite:
    _kwargs.update(pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow, pool_recycle=1800)

engine = create_async_engine(settings.database_url, **_kwargs)

if settings.is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        yield s


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as s:
        try:
            yield s
            # A timed-out/replaced worker must never commit into a newer execution.
            from app.services.watchdog import job_lease
            lease = job_lease.get()
            if lease:
                import asyncio

                from sqlalchemy import select

                from app.models import Simulation
                token = (await s.execute(select(Simulation.execution_token).where(Simulation.id == lease[0]).with_for_update())).scalar_one_or_none()
                if token != lease[1]:
                    await s.rollback()
                    raise asyncio.CancelledError("This workflow execution was replaced or expired")
            await s.commit()
        except BaseException:
            await s.rollback()
            raise
