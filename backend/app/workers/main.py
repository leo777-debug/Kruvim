"""arq worker entrypoint:  arq app.workers.main.WorkerSettings

Scale horizontally by running more worker containers; each handles `KRUVIM_WORKER_MAX_JOBS` jobs."""
from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

from app.core.config import settings
from app.core.logging import setup_logging
from app.services.datapool import ensure_platform_connectors

from . import tasks


async def startup(ctx):
    setup_logging()
    await ensure_platform_connectors()


class WorkerSettings:
    functions = [tasks.build_graph, tasks.prepare_environment, tasks.run_simulation, tasks.generate_report, tasks.run_survey,
                 tasks.refresh_datapool, tasks.monitoring_tick, tasks.run_connector, tasks.build_population]
    cron_jobs = [cron(tasks.refresh_datapool, minute=set(range(0, 60, 10)), run_at_startup=True, unique=True),
                 cron(tasks.monitoring_tick, minute=set(range(5, 60, 10)), unique=True)]
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    max_jobs = settings.worker_max_jobs
    job_timeout = 6 * 3600
    keep_result = 3600
    on_startup = startup
