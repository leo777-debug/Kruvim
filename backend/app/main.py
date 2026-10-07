"""Kruvim API.

    uvicorn app.main:app                       (dev, single process: in-memory queue + events)
    gunicorn app.main:app -k uvicorn.workers.UvicornWorker   (prod, with KRUVIM_REDIS_URL + arq workers)
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import select

from app.api.routes import (
    analytics,
    auth,
    collab,
    creator,
    datapool,
    monitoring,
    platform,
    projects,
    runs,
    sharing,
    simulations,
    workspace,
)
from app.core import errors
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestContextMiddleware
from app.core.redis import close_redis

log = logging.getLogger("kruvim")


async def _bootstrap():
    from app.db.session import engine, session_scope
    from app.models import Base, Simulation, User
    if settings.env == "test":
        async with engine.begin() as c:
            await c.run_sync(Base.metadata.create_all)
    elif settings.is_sqlite:
        import asyncio

        from app.db.migrate import upgrade_head
        await asyncio.to_thread(upgrade_head)
    if settings.first_superuser_email and settings.first_superuser_password:
        from app.core.security import hash_password
        async with session_scope() as s:
            u = (await s.execute(select(User).where(User.email == settings.first_superuser_email.lower()))).scalar_one_or_none()
            if u is None:
                s.add(User(email=settings.first_superuser_email.lower(), name="Administrator",
                           password_hash=hash_password(settings.first_superuser_password), is_superuser=True))
    if not settings.redis_url:
        # Single-process mode: jobs died with the previous process; mark them so the UI does not hang.
        from sqlalchemy import update
        async with session_scope() as s:
            await s.execute(update(Simulation).where(Simulation.status.in_(["building_graph", "preparing", "queued", "running", "paused"]))
                            .values(status="failed", error="Interrupted by a server restart. Run this step again."))
        from app.services.datapool import ensure_platform_connectors
        await ensure_platform_connectors()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(json_logs=settings.env != "development")
    await _bootstrap()
    scheduler = None
    watcher = None
    if settings.env != 'test':
        import asyncio

        async def watch_loop():
            from app.services.watchdog import check
            while True:
                try:
                    await check()
                except Exception:
                    log.exception('run watchdog failed')
                await asyncio.sleep(30)
        # The API can recover runs even when every worker is unavailable.
        watcher = asyncio.create_task(watch_loop())
    if not settings.redis_url and settings.env != "test":
        import asyncio

        from app.services.datapool import run_due

        async def loop():
            memory_day = None
            while True:
                try:
                    from app.services.watchdog import check
                    await check()
                except Exception:
                    log.exception("run watchdog failed")
                try:
                    await run_due()
                    from app.services.datapool.archive import compress_old
                    from app.services.datapool.cultural import synthesize_daily
                    await synthesize_daily()
                    await compress_old()
                except Exception:
                    log.exception("data pool refresh failed")
                try:
                    from app.services.monitoring import tick
                    await tick()
                except Exception:
                    log.exception("monitoring tick failed")
                try:
                    from app.services.social_sync import sync_due
                    await sync_due()
                except Exception:
                    log.exception("analytics sync failed")
                try:
                    from app.db.base import utcnow
                    from app.services.agent_memory import consolidate
                    today = utcnow().date()
                    if memory_day != today:
                        await consolidate()
                        memory_day = today
                except Exception:
                    log.exception("agent memory consolidation failed")
                await asyncio.sleep(600)
        scheduler = asyncio.create_task(loop())
    try:
        yield
    finally:
        if watcher:
            watcher.cancel()
            from contextlib import suppress
            with suppress(asyncio.CancelledError):
                await watcher
        if scheduler:
            scheduler.cancel()
            from contextlib import suppress
            with suppress(asyncio.CancelledError):
                await scheduler
        await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(title="Kruvim API", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json",
                  redoc_url=None)
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"],
                       allow_headers=["*"], expose_headers=["x-request-id"])
    app.add_middleware(RequestContextMiddleware)
    errors.install(app)
    for r in (auth.router, workspace.router, projects.router, simulations.router, collab.router, creator.router, analytics.router, monitoring.router, runs.router, sharing.router, datapool.router, platform.router):
        app.include_router(r, prefix="/api/v1")
    app.add_api_route("/healthz", platform.healthz, include_in_schema=False)
    app.add_api_route("/readyz", platform.readyz, include_in_schema=False)
    app.add_api_route("/metrics", platform.metrics, include_in_schema=False)
    return app


app = create_app()
