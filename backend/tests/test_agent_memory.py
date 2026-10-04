"""Native agent memory: persistence, isolation, snapshots and deterministic policies."""
import asyncio
import importlib.util
import io
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


async def memory_run(auth, agents=2):
    from app.db.session import session_scope
    from app.models import Project, SimAgent, Simulation
    async with session_scope() as s:
        org_id = auth[1]["orgs"][0]["id"]
        project = Project(org_id=org_id, name="Memory tests")
        s.add(project)
        await s.flush()
        sim = Simulation(org_id=org_id, project_id=project.id, status="completed", card={"topics": {"fitness": 1}},
                         content={"creator_subject": "gym"}, results={"score": {"mean": 7}})
        s.add(sim)
        await s.flush()
        for i in range(agents):
            s.add(SimAgent(simulation_id=sim.id, ref=f"p:{i}", kind="voice", name=f"Voice {i}", handle=f"voice{i}",
                persona={"age": 22, "gender": "female", "region": "AE"}, config={}, reaction={"score": 8, "drop_segment": 2},
                state={"opinion": 7}, followers=20))
    return org_id, sim.id


async def test_memory_migration_from_previous_head(monkeypatch, tmp_path):
    from app.core.config import settings
    root = Path(__file__).parents[1]
    db = tmp_path / "migration.db"
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///" + db.as_posix())
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    await asyncio.to_thread(command.upgrade, cfg, "0006")
    engine = create_engine("sqlite:///" + db.as_posix())
    try:
        assert "agent_memories" not in inspect(engine).get_table_names()
        await asyncio.to_thread(command.upgrade, cfg, "head")
        tables = inspect(engine).get_table_names()
        assert "agent_memories" in tables and "agent_creator_affinity" in tables
        assert {"org_id", "population_ref", "embedding", "superseded_by", "recall_count"} <= {
            x["name"] for x in inspect(engine).get_columns("agent_memories")}
        assert "ix_agent_memories_person" in {x["name"] for x in inspect(engine).get_indexes("agent_memories")}
        await asyncio.to_thread(command.downgrade, cfg, "0006")
        assert "agent_memories" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_memory_postgres_migration_contract():
    # Real PostgreSQL execution is also available through tools/verify_memory_postgres.py.
    path = Path(__file__).parents[1] / "migrations/versions/20261004_0007_agent_memories.py"
    spec = importlib.util.spec_from_file_location("agent_memory_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        module.upgrade()
    sql = output.getvalue()
    assert "VECTOR(128)" in sql and "USING hnsw (embedding vector_cosine_ops)" in sql
    assert "org_id, population_ref" in sql and "ON DELETE CASCADE" in sql


async def test_batched_writer_is_idempotent_private_and_deterministic(auth):
    from unittest.mock import AsyncMock

    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models import Action, AgentCreatorAffinity, AgentMemory, Post
    from app.services.agent_memory import write_run
    from app.services.llm import Usage
    org, sim = await memory_run(auth, 21)
    async with session_scope() as s:
        s.add_all([Post(simulation_id=sim, author_ref="ext:real", platform="feed", kind="external", content="PRIVATE REAL POST TEXT"),
                   Post(simulation_id=sim, author_ref="p:0", platform="feed", kind="comment", content="RAW GENERATED COMMENT"),
                   Action(simulation_id=sim, round=1, platform="feed", actor_ref="p:0", action="MUTE", target_ref="s:other")])
    llm = type("Writer", (), {"is_dry": False, "complete_json": AsyncMock(return_value={})})()
    assert await write_run(org, sim, llm, Usage()) > 60
    assert llm.complete_json.await_count == 2
    assert await write_run(org, sim, llm, Usage()) == 0
    async with session_scope() as s:
        rows = (await s.execute(select(AgentMemory).where(AgentMemory.org_id == org))).scalars().all()
        aff = (await s.execute(select(AgentCreatorAffinity).where(AgentCreatorAffinity.org_id == org))).scalars().all()
        assert len(aff) == 21 and all(a.familiarity == 1 for a in aff)
        assert any(r.kind == "relationship" for r in rows)
        assert all("RAW" not in r.text and "PRIVATE" not in r.text and r.source_simulation_id == sim for r in rows)
    assert "PRIVATE REAL POST TEXT" not in str(llm.complete_json.call_args_list)
    assert "RAW GENERATED COMMENT" not in str(llm.complete_json.call_args_list)
    from app.models import SimAgent, Simulation
    from app.services.agent_memory import rule_memories
    async with session_scope() as s:
        agent = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim, SimAgent.ref == "p:0"))).scalar_one()
        run = await s.get(Simulation, sim)
        assert rule_memories(agent, run, [], [], 0) == rule_memories(agent, run, [], [], 0)
