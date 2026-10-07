"""Dedicated connector queue: arq app.workers.connectors.ConnectorWorkerSettings."""
import os
from arq.connections import RedisSettings

from app.core.config import settings
from app.workers.main import startup
from app.workers.tasks import run_connector


class ConnectorWorkerSettings:
    health_check_interval = 30
    health_check_key = f"kruvim:connector:{os.getenv('HOSTNAME', 'local')}:health"
    functions = [run_connector]
    queue_name = "kruvim:connectors"
    redis_settings = RedisSettings.from_dsn(settings.redis_url or "redis://localhost:6379")
    max_jobs = settings.connector_concurrency
    job_timeout = 140
    keep_result = 600
    on_startup = startup
