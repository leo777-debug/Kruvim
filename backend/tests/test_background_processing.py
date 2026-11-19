from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.core.errors import AppError
from app.services import cloud_jobs, jobs
from app.workers import maintenance


class Queue:
    def __init__(self):
        self.deliveries = {}

    async def enqueue_job(self, name, **kwargs):
        key = kwargs["_job_id"]
        if key in self.deliveries:
            return None
        self.deliveries[key] = (name, kwargs)
        return key


async def test_schedule_deduplicates_refresh_and_worker_and_recovers_missed_ticks():
    queue = Queue()
    now = datetime(2026, 11, 18, 2, 29, tzinfo=UTC)
    assert await maintenance.schedule_due(queue, now) == 9
    assert await maintenance.schedule_due(queue, now) == 0
    # Watchdog, mail, token and daily memory jobs cross a slot at 02:30 UTC,
    # along with the ten-minute data refresh.
    assert await maintenance.schedule_due(queue, now + timedelta(minutes=1)) == 5
    assert {item[0] for item in queue.deliveries.values()} == {row[0] for row in maintenance.SCHEDULE}
    assert all(item[1]["_queue_name"] == "kruvim:maintenance" for item in queue.deliveries.values())
    # A late scheduler still enqueues the latest slots after an outage.
    assert await maintenance.schedule_due(queue, now + timedelta(hours=3)) == 8


async def test_all_scheduled_jobs_are_executable_by_worker():
    from app.workers.main import MaintenanceWorkerSettings, WorkerSettings
    registered = {fn.__name__ for fn in MaintenanceWorkerSettings.functions}
    assert {row[0] for row in maintenance.SCHEDULE} <= registered
    assert WorkerSettings.job_timeout > settings.simulation_max_duration_seconds
    assert MaintenanceWorkerSettings.keep_result > 86400
    assert MaintenanceWorkerSettings.queue_name == "kruvim:maintenance"


async def test_worker_rejects_settings_that_would_route_jobs_in_process(monkeypatch):
    from app.workers.main import startup
    monkeypatch.setattr(settings, "redis_url", None)
    with pytest.raises(RuntimeError, match="KRUVIM_REDIS_URL"):
        await startup({})
    monkeypatch.setattr(settings, "redis_url", "redis://example")
    monkeypatch.setattr(settings, "serverless", True)
    with pytest.raises(RuntimeError, match="KRUVIM_SERVERLESS"):
        await startup({})
    monkeypatch.setattr(settings, "redis_url", None)


async def test_hosted_workloads_fail_before_persistence_without_external_workers(monkeypatch):
    monkeypatch.setattr(settings, "serverless", True)
    monkeypatch.setattr(settings, "redis_url", None)
    cloud_enqueue = AsyncMock()
    monkeypatch.setattr(cloud_jobs, "enqueue", cloud_enqueue)
    with pytest.raises(AppError, match="external Redis workers"):
        await jobs.enqueue("run_simulation", sim_id="example")
    cloud_enqueue.assert_not_awaited()


@pytest.mark.parametrize("stage", ["queue_graph", "queue_environment", "queue_run"])
async def test_missing_workers_does_not_change_workflow_state(stage, monkeypatch):
    from types import SimpleNamespace

    from app.services import lifecycle
    monkeypatch.setattr(settings, "serverless", True)
    monkeypatch.setattr(settings, "redis_url", None)
    session = AsyncMock()
    simulation = SimpleNamespace(status="completed", results={"preserved": True})
    with pytest.raises(AppError, match="external Redis workers"):
        await getattr(lifecycle, stage)(session, simulation)
    assert simulation.status == "completed" and simulation.results == {"preserved": True}
    session.commit.assert_not_awaited()


async def test_hosted_workload_is_durable_before_redis_delivery(monkeypatch):
    from app.db.session import session_scope
    from app.models import CloudJob
    from app.services import outbox
    with monkeypatch.context() as config:
        config.setattr(settings, "serverless", True)
        config.setattr(settings, "redis_url", "redis://example")
        job_id = await jobs.enqueue("run_simulation", sim_id="example", delay=5)
    async with session_scope() as session:
        job = await session.get(CloudJob, job_id)
        assert job.status == "redis_pending" and job.payload == {"sim_id": "example"}
    pool = AsyncMock()
    await outbox.deliver(pool)
    pool.enqueue_job.assert_not_awaited()  # delayed jobs stay durable until due


async def test_refresh_authenticates_and_only_enqueues_maintenance(client, monkeypatch):
    monkeypatch.setattr(settings, "cron_secret", "scheduler-test")
    monkeypatch.setattr(settings, "redis_url", "redis://example")
    pool = AsyncMock()
    monkeypatch.setattr(jobs, "_arq_pool", AsyncMock(return_value=pool))
    assert (await client.post("/internal/refresh")).status_code == 401
    response = await client.post("/internal/refresh", headers={"Authorization": "Bearer scheduler-test"})
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "mode": "external-workers", "dispatched": 9}
    assert {call.args[0] for call in pool.enqueue_job.await_args_list} == {row[0] for row in maintenance.SCHEDULE}
    monkeypatch.setattr(settings, "redis_url", None)
    assert (await client.post("/internal/refresh", headers={"Authorization": "Bearer scheduler-test"})).status_code == 503


async def test_legacy_http_workloads_cannot_run_on_hosted_functions(client, monkeypatch):
    monkeypatch.setattr(settings, "serverless", True)
    monkeypatch.setattr(settings, "cron_secret", "scheduler-test")
    response = await client.post("/internal/jobs/legacy", headers={"Authorization": "Bearer scheduler-test"})
    assert response.status_code == 503
    with pytest.raises(AppError, match="external Redis workers"):
        await cloud_jobs.enqueue("run_simulation", 0, {"sim_id": "example"})


@pytest.mark.parametrize("missing", [None, "worker", "connector", "maintenance"])
async def test_production_readiness_requires_every_worker_tier(monkeypatch, missing):
    from app.api.routes import platform

    class Redis:
        ping = AsyncMock()
        exists = AsyncMock(return_value=1)

        async def scan_iter(self, *, match, count):
            if f":{missing}:" not in match:
                yield match.replace("*", "fixture")

    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setattr(platform, "get_redis", lambda: Redis())
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["0021"]
    session.execute.return_value = result
    if missing:
        with pytest.raises(AppError, match="not ready") as exc:
            await platform.readyz(session)
        assert exc.value.status == 503 and exc.value.details["workers"][missing] is False
    else:
        assert (await platform.readyz(session))["workers"] == {
            "worker": True, "connector": True, "maintenance": True,
        }


async def test_hosted_readiness_rejects_old_database_even_without_production_env(monkeypatch):
    from app.api.routes import platform
    monkeypatch.setattr(settings, "serverless", True)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["0019"]
    session.execute.return_value = result
    with pytest.raises(AppError, match="Database revision") as exc:
        await platform.readyz(session)
    assert exc.value.status == 503


async def test_health_identifies_exact_build_without_exposing_arbitrary_environment(monkeypatch):
    from app.api.routes import platform
    monkeypatch.setenv("KRUVIM_RELEASE_SHA", "a" * 40)
    assert (await platform.healthz())["release"]["commit"] == "a" * 40
    monkeypatch.setenv("KRUVIM_RELEASE_SHA", "not-a-commit")
    assert (await platform.healthz())["release"]["commit"] == "local"


def test_readiness_revision_matches_the_single_migration_head():
    from pathlib import Path

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app.core.release import EXPECTED_REVISION
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parents[1] / "migrations"))
    assert ScriptDirectory.from_config(config).get_heads() == [EXPECTED_REVISION]


async def test_readiness_does_not_accept_workers_from_another_commit(monkeypatch):
    from fnmatch import fnmatch

    from app.api.routes import platform
    monkeypatch.setattr(settings, "env", "production")
    monkeypatch.setenv("KRUVIM_RELEASE_SHA", "a" * 40)

    class OldWorkers:
        ping = AsyncMock()
        exists = AsyncMock(return_value=1)

        async def scan_iter(self, *, match, count):
            for kind in ("worker", "connector", "maintenance"):
                key = f"kruvim:{kind}:{'b' * 40}:old-host:health"
                if fnmatch(key, match):
                    yield key

    monkeypatch.setattr(platform, "get_redis", lambda: OldWorkers())
    result = MagicMock()
    result.scalars.return_value.all.return_value = ["0021"]
    session = AsyncMock()
    session.execute.return_value = result
    with pytest.raises(AppError, match="workers are not ready"):
        await platform.readyz(session)
