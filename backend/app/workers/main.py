"""arq worker entrypoint:  arq app.workers.main.WorkerSettings

Scale horizontally by running more worker containers; each handles `KRUVIM_WORKER_MAX_JOBS` jobs."""
from __future__ import annotations

import asyncio
from contextlib import suppress

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.release import worker_health_key
from app.services import outbox
from app.services.datapool import ensure_platform_connectors

from . import maintenance, tasks


async def startup(ctx):
    if not settings.redis_url:
        raise RuntimeError("Set KRUVIM_REDIS_URL on every external worker.")
    if settings.serverless:
        raise RuntimeError("External workers require KRUVIM_SERVERLESS=false.")
    setup_logging()
    await ensure_platform_connectors()


async def start_main(ctx):
    await startup(ctx)
    ctx["outbox_poller"] = asyncio.create_task(outbox.poll(ctx["redis"]))


async def stop_main(ctx):
    ctx["outbox_poller"].cancel()
    with suppress(asyncio.CancelledError):
        await ctx["outbox_poller"]


class WorkerSettings:
    health_check_interval = 30
    health_check_key = worker_health_key("worker")
    functions = [outbox.run_outbox_job, tasks.build_graph, tasks.prepare_environment, tasks.run_simulation, tasks.generate_report, tasks.run_survey,
                 tasks.refresh_datapool, tasks.monitoring_tick, tasks.run_connector, tasks.build_population, tasks.resume_autopilot]
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    max_jobs = settings.worker_max_jobs
    job_timeout = max(6 * 3600, settings.simulation_max_duration_seconds + 60)
    allow_abort_jobs = True
    keep_result = 3600
    on_startup = start_main
    on_shutdown = stop_main


class MaintenanceWorkerSettings(WorkerSettings):
    health_check_key = worker_health_key("maintenance")
    queue_name = "kruvim:maintenance"
    functions = [tasks.refresh_datapool, tasks.monitoring_tick,
                 maintenance.sync_analytics, maintenance.maintain_archive,
                 maintenance.consolidate_agent_memory, maintenance.watch_runs,
                 maintenance.archive_snapshots, maintenance.dispatch_mail, maintenance.maintain_token_budget,
                 maintenance.maintenance_tick]
    cron_jobs = [cron(maintenance.maintenance_tick, minute=set(range(60)), unique=True, run_at_startup=True)]
    keep_result = 172800
    on_startup = startup
    on_shutdown = None
