from datetime import timedelta

import pytest
from sqlalchemy import select

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
