"""arq worker entrypoint:  arq app.workers.main.WorkerSettings

Scale horizontally by running more worker containers; each handles `KRUVIM_WORKER_MAX_JOBS` jobs."""
from __future__ import annotations
import os

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.datapool import ensure_platform_connectors

from . import tasks


async def startup(ctx):
    setup_logging()
    await ensure_platform_connectors()


async def sync_analytics(ctx):
    from app.services.social_sync import sync_due
    await sync_due()


async def maintain_archive(ctx):
    from app.services.datapool.archive import compress_old
    from app.services.datapool.cultural import synthesize_daily
    await synthesize_daily()
    await compress_old()


async def consolidate_agent_memory(ctx):
    from app.services.agent_memory import consolidate
    return await consolidate()


async def watch_runs(ctx):
    from app.services.watchdog import check
    return await check()


class WorkerSettings:
    health_check_interval = 30
    health_check_key = f"kruvim:worker:{os.getenv('HOSTNAME', 'local')}:health"
    functions = [tasks.build_graph, tasks.prepare_environment, tasks.run_simulation, tasks.generate_report, tasks.run_survey,
                 tasks.refresh_datapool, tasks.monitoring_tick, tasks.run_connector, tasks.build_population, tasks.resume_autopilot]
    cron_jobs = [cron(tasks.refresh_datapool, minute=set(range(0, 60, 10)), run_at_startup=True, unique=True),
                 cron(tasks.monitoring_tick, minute=set(range(5, 60, 10)), unique=True),
                 cron(sync_analytics, minute=set(range(3, 60, 10)), unique=True)]
    cron_jobs.append(cron(maintain_archive, minute=15, unique=True))
    cron_jobs.append(cron(consolidate_agent_memory, hour=2, minute=30, unique=True))
    cron_jobs.append(cron(watch_runs, minute=set(range(60)), unique=True, run_at_startup=True))
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    max_jobs = settings.worker_max_jobs
    job_timeout = 6 * 3600
    allow_abort_jobs = True
    keep_result = 3600
    on_startup = startup
