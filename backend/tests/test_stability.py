from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import DataSource, Simulation
from app.services.datapool.base import SignalItem
from app.services.datapool.connectors import REGISTRY
from app.services.datapool.context import build_snapshot_data, weighted_context
from app.services.datapool.retrieval import prepare_retrieval
from app.services.datapool.runner import ensure_platform_connectors, store_signals
from app.services.llm import BaseLLM, LLMError, ProviderSettings, Usage, make_llm
from app.services.sources import ensure_sources
from app.services.watchdog import check


def test_compose_worker_health_checks():
    from pathlib import Path

    from app.workers.connectors import ConnectorWorkerSettings
    from app.workers.main import WorkerSettings
    assert WorkerSettings.health_check_interval == ConnectorWorkerSettings.health_check_interval == 30
    assert WorkerSettings.health_check_key != ConnectorWorkerSettings.health_check_key
    compose = (Path(__file__).parents[2] / 'docker-compose.yml').read_text()
    assert '"app.workers.main.WorkerSettings", "--check"' in compose
    assert '"app.workers.connectors.ConnectorWorkerSettings", "--check"' in compose


async def test_browser_seed_pool_does_not_cross_event_loops(tmp_path):
    """Reproduce the closed seed-loop queue under contention, then verify disposal."""
    import asyncio

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    async def exercise(engine):
        async with engine.connect():
            async def waiting():
                async with engine.connect() as conn:
                    return await conn.scalar(text('SELECT 1'))
            task = asyncio.create_task(waiting())
            # Wait until the pool's waiter has actually entered its queue.
            while not task.done() and not engine.pool._pool._queue._getters:
                await asyncio.sleep(0)
        return await task
    def verify():
        for dispose in (False, True):
            engine = create_async_engine('sqlite+aiosqlite:///' + (tmp_path / f'pool-{dispose}.db').as_posix(),
                pool_size=1, max_overflow=0)
            async def seed(engine=engine, dispose=dispose):
                assert await exercise(engine) == 1
                if dispose:
                    await engine.dispose()
            asyncio.run(seed())
            async def server(engine=engine, dispose=dispose):
                try:
                    if dispose:
                        assert await exercise(engine) == 1
                    else:
                        with pytest.raises(RuntimeError, match='different event loop'):
                            await exercise(engine)
                finally:
                    await engine.dispose()
            asyncio.run(server())
    await asyncio.to_thread(verify)


async def test_disconnected_stream_finishes_database_cleanup(monkeypatch, tmp_path):
    """AnyIO level cancellation must not strand a pooled transaction on SSE close."""
    import anyio
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db import session as database
    engine = create_async_engine('sqlite+aiosqlite:///' + (tmp_path / 'disconnect.db').as_posix(), pool_size=1, max_overflow=0)
    async with engine.begin() as connection:
        await connection.execute(text('CREATE TABLE cleanup (value INTEGER)'))
    monkeypatch.setattr(database, 'SessionLocal', async_sessionmaker(engine, expire_on_commit=False))
    try:
        for scoped in (False, True):
            with anyio.CancelScope() as disconnected:
                if scoped:
                    async with database.session_scope() as session:
                        await session.execute(text('INSERT INTO cleanup VALUES (1)'))
                        disconnected.cancel()
                        await anyio.lowlevel.checkpoint()
                else:
                    dependency = database.get_session()
                    session = await anext(dependency)
                    await session.execute(text('INSERT INTO cleanup VALUES (1)'))
                    disconnected.cancel()
                    await dependency.aclose()
            assert engine.pool.checkedout() == 0
            with anyio.fail_after(2):
                async with engine.begin() as connection:
                    assert (await connection.execute(text('SELECT count(*) FROM cleanup'))).scalar() == 0
                    await connection.execute(text('INSERT INTO cleanup VALUES (2)'))
                    await connection.execute(text('DELETE FROM cleanup'))
    finally:
        await engine.dispose()


async def test_event_stream_releases_authorisation_connection(client, auth):
    from types import SimpleNamespace

    import anyio
    from starlette.requests import Request

    from app.api.routes.simulations import events
    from app.db.session import SessionLocal, engine
    from app.services.events import bus
    h, account = auth
    project = (await client.post('/projects', headers=h, json={'name': 'Streaming'})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
        json={'content': {'type': 'text', 'text': 'Streaming fixture'}})).json()
    request = Request({'type': 'http', 'headers': []})
    await bus.publish(sim['id'], 'graph.progress', {'message': 'Fixture'})
    before = engine.pool.checkedout()
    async with SessionLocal() as session:
        response = await events(sim['id'], request, SimpleNamespace(org_id=account['orgs'][0]['id']), session)
        assert engine.pool.checkedout() == before
        assert not session.in_transaction()
        first = None
        with anyio.CancelScope() as disconnected:
            disconnected.cancel()
            first = await anext(response.body_iterator)
        assert first is not None and 'graph.progress' in first
        assert len(bus._local[sim['id']]) == 1
        await response.body_iterator.aclose()
        assert not bus._local[sim['id']]
        assert engine.pool.checkedout() == before


@pytest.mark.parametrize('during_subscribe', [False, True])
async def test_disconnected_stream_closes_redis_subscription(client, auth, monkeypatch, during_subscribe):
    import anyio

    from app.services import events
    h, _ = auth
    project = (await client.post('/projects', headers=h, json={'name': 'Redis stream'})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
        json={'content': {'type': 'text', 'text': 'Redis fixture'}})).json()
    await events.bus.publish(sim['id'], 'graph.progress', {'message': 'Fixture'})
    class Subscription:
        closed = False
        async def subscribe(self, channel):
            await anyio.lowlevel.checkpoint()
        async def unsubscribe(self, channel):
            await anyio.lowlevel.checkpoint()
        async def aclose(self):
            await anyio.lowlevel.checkpoint()
            self.closed = True
    subscription = Subscription()
    class Redis:
        def pubsub(self):
            return subscription
    monkeypatch.setattr(events, 'get_redis', Redis)
    stream = events.bus.stream(sim['id'])
    if during_subscribe:
        with anyio.CancelScope() as disconnected:
            disconnected.cancel()
            await anext(stream)
    else:
        assert 'graph.progress' in await anext(stream)
        with anyio.CancelScope() as disconnected:
            disconnected.cancel()
            await stream.aclose()
    assert subscription.closed


async def test_api_watchdog_runs_without_workers_and_stops_on_shutdown(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from app import main
    started = asyncio.Event()
    async def checked():
        started.set()
    with monkeypatch.context() as patch:
        patch.setattr(settings, 'env', 'production')
        patch.setattr(settings, 'redis_url', 'redis://unused')
        patch.setattr(main, '_bootstrap', AsyncMock())
        patch.setattr(main, 'close_redis', AsyncMock())
        patch.setattr('app.services.watchdog.check', checked)
        before = set(asyncio.all_tasks())
        async with main.lifespan(main.app):
            await asyncio.wait_for(started.wait(), 2)
            assert any(task not in before for task in asyncio.all_tasks())
        assert not {task for task in asyncio.all_tasks() if task not in before}


async def test_default_registry_has_weights_and_personal_signals(client, auth):
    h, session = auth
    await ensure_platform_connectors()
    async with session_scope() as s:
        await ensure_sources(s)
        rows = (await s.execute(select(DataSource))).scalars().all()
    assert set(REGISTRY) <= {r.key for r in rows}
    assert all(r.reliability > 0 for r in rows if r.key in REGISTRY)
    await store_signals("wikipedia", [SignalItem("trend", "SA", "Fitness workouts", lang="en", value=100)])
    await store_signals("mastodon", [SignalItem("social_trend", "SA", "Fitness posts", lang="en")])
    snapshot = await build_snapshot_data("SA", utcnow())
    snapshots, _ = weighted_context({"SA": snapshot})
    persona = {"region": "SA", "age": 25, "language": "English", "interests": [{"label": "Fitness"}], "platforms": ["TikTok"]}
    out, _ = await prepare_retrieval(session["orgs"][0]["id"], [persona], {"title": "Fitness"}, snapshots, make_llm(ProviderSettings()), Usage())
    assert out[0] and out[0][0]["source"] == "wikipedia"
    health = (await client.get("/datapool/health", headers=h)).json()
    assert health["usable_signals"] >= 1
    assert any(w["source"] == "mastodon" for w in health["warnings"])


async def test_json_failure_is_bounded_and_counted():
    class BadJSON(BaseLLM):
        async def complete(self, **kw):
            return "[1, 2]"
    usage = Usage()
    with pytest.raises(LLMError, match="valid JSON"):
        await BadJSON(ProviderSettings()).complete_json(system="x", user="y", role="voice", max_tokens=30, usage=usage)
    assert usage.failed == 1


async def test_job_deadline_migration_from_previous_head(tmp_path, monkeypatch):
    import asyncio
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from app.core.config import settings
    root = Path(__file__).parents[1]
    db = tmp_path / 'previous.db'
    monkeypatch.setattr(settings, 'database_url', 'sqlite+aiosqlite:///' + db.as_posix())
    cfg = Config(str(root / 'alembic.ini'))
    cfg.set_main_option('script_location', str(root / 'migrations'))
    for revision in ('0010', 'head', 'head'):
        await asyncio.to_thread(command.upgrade, cfg, revision)
    engine = create_engine('sqlite:///' + db.as_posix())
    try:
        assert {'job_deadline', 'execution_token'} <= {c['name'] for c in inspect(engine).get_columns('simulations')}
    finally:
        engine.dispose()


async def test_expired_worker_cannot_commit(client, auth):
    import asyncio

    from app.services.watchdog import job_lease
    h, _ = auth
    project = (await client.post("/projects", headers=h, json={"name": "Fence"})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
        json={"content": {"type": "text", "text": "Test"}})).json()
    token = job_lease.set((sim["id"], "old-worker"))
    try:
        with pytest.raises(asyncio.CancelledError):
            async with session_scope() as s:
                row = await s.get(Simulation, sim["id"])
                row.status = "completed"
    finally:
        job_lease.reset(token)
    assert (await client.get(f"/simulations/{sim['id']}", headers=h)).json()["status"] == "draft"


async def test_watchdog_recovers_lost_autopilot_handoff_but_keeps_manual_pause(client, auth):
    from app.services.watchdog import fail_expired
    h, _ = auth
    project = (await client.post('/projects', headers=h, json={'name': 'Handoffs'})).json()
    ids = []
    for autopilot in (False, True):
        sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
            json={'content': {'type': 'text', 'text': 'Fixture'}})).json()
        async with session_scope() as s:
            row = await s.get(Simulation, sim['id'])
            row.status = 'graph_ready'
            row.config = {'autopilot': autopilot}
        ids.append(sim['id'])
    assert await check(utcnow() + timedelta(seconds=settings.simulation_max_duration_seconds + 1)) == 1
    assert (await client.get(f'/simulations/{ids[0]}', headers=h)).json()['status'] == 'graph_ready'
    assert (await client.get(f'/simulations/{ids[1]}', headers=h)).json()['status'] == 'failed'
    async with session_scope() as s:
        row = await s.get(Simulation, ids[1])
        row.status, row.execution_token = 'running', 'replacement'
    await fail_expired(ids[1], 'expired')
    assert (await client.get(f'/simulations/{ids[1]}', headers=h)).json()['status'] == 'running'
    async with session_scope() as s:
        row = await s.get(Simulation, ids[1])
        row.status, row.report_status = 'completed', 'done'
    await fail_expired(ids[1], 'replacement')
    assert (await client.get(f'/simulations/{ids[1]}', headers=h)).json()['status'] == 'completed'


async def test_watchdog_and_tenant_retry(client, auth):
    h, _ = auth
    project = (await client.post("/projects", headers=h, json={"name": "Watchdog"})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h,
        json={"content": {"type": "text", "text": "A helpful workout"}, "overrides": {"voice": 10, "crowd": 50, "hours": 1, "listening": False}})).json()
    async with session_scope() as s:
        row = await s.get(Simulation, sim["id"])
        row.status = "running"
        row.job_deadline = utcnow() - timedelta(seconds=1)
    assert await check() == 1
    failed = (await client.get(f"/simulations/{sim['id']}", headers=h)).json()
    assert failed["status"] == "failed" and "Retry" in failed["error"]
    response = await client.post(f"/simulations/{sim['id']}/retry", headers=h)
    assert response.status_code == 200, response.text
    from app.services.jobs import drain
    await drain()
    assert (await client.get(f"/simulations/{sim['id']}", headers=h)).json()["report_status"] == "done"


async def test_agent_failure_falls_back_without_failing_run(client, auth, monkeypatch):
    from test_e2e_dry import SCRIPT

    from app.services.llm import DryRunLLM
    from app.workers import tasks
    h, _ = auth
    project = (await client.post("/projects", headers=h, json={"name": "Fallback"})).json()
    sim = (await client.post(f"/projects/{project['id']}/simulations", headers=h, json={
        "content": {"type": "video", "transcript": SCRIPT}, "audience": {"regions": ["AE"]},
        "overrides": {"voice": 10, "crowd": 100, "hours": 1, "stakeholders": 0, "listening": False}})).json()
    from app.services.jobs import drain
    await client.post(f"/simulations/{sim['id']}/graph", headers=h)
    await drain()
    await client.post(f"/simulations/{sim['id']}/environment", headers=h)
    await drain()
    original = tasks._llm_for
    class FailedVoice(DryRunLLM):
        is_dry = False
        async def complete(self, **kw):
            raise LLMError("Temporary model failure")
    async def failed(org_id):
        resolved, _ = await original(org_id)
        return resolved, FailedVoice(resolved.settings)
    monkeypatch.setattr(tasks, "_llm_for", failed)
    await client.post(f"/simulations/{sim['id']}/start", headers=h)
    await drain()
    result = (await client.get(f"/simulations/{sim['id']}", headers=h)).json()
    assert result["status"] == "completed", result.get("error")
    assert result["results"]["reliability"]["fallback_calls"] >= 10
    assert result["progress"]["quick_read"]["sample_size"] == 5
    assert result["progress"]["quick_read"]["preliminary"] is True
    from app.models import SimEvent
    async with session_scope() as s:
        events = (await s.execute(select(SimEvent).where(SimEvent.simulation_id == sim['id']).order_by(SimEvent.seq))).scalars().all()
    types = [event.type for event in events]
    assert types.index('simulation.quick_read') < types.index('simulation.completed')
