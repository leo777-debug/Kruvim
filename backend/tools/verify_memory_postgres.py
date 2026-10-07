"""Verify migration 0006 -> head + vector recall in a newly created disposable PostgreSQL DB.

Set KRUVIM_MEMORY_TEST_PG_URL to a PostgreSQL server URL with CREATE DATABASE and vector privileges.
The named database in that URL is only used to create/drop a random scratch database. Its tables are never changed.
"""
import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

from sqlalchemy.engine import make_url


async def check():
    import asyncpg
    url = make_url(os.environ["KRUVIM_MEMORY_TEST_PG_URL"])
    if not url.drivername.startswith("postgresql"):
        raise ValueError("A PostgreSQL server URL is required")
    name = "kruvim_memory_verify_" + uuid.uuid4().hex[:12]
    server = await asyncpg.connect(url.set(drivername="postgresql").render_as_string(hide_password=False), timeout=10)
    created = False
    try:
        await server.execute(f'CREATE DATABASE "{name}"')
        created = True
        scratch = url.set(database=name, drivername="postgresql+asyncpg")
        env = {**os.environ, "KRUVIM_DATABASE_URL": scratch.render_as_string(hide_password=False), "KRUVIM_REDIS_URL": "",
               "KRUVIM_ENV": "test", "KRUVIM_LLM_API_KEY": ""}
        root = Path(__file__).parents[1]
        for revision in ("0006", "head"):
            result = await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "alembic", "upgrade", revision],
                cwd=root, env=env, capture_output=True, timeout=120)
            if result.returncode:
                raise RuntimeError(f"Migration to {revision} failed; no server credentials are printed")
        connection = await asyncpg.connect(scratch.set(drivername="postgresql").render_as_string(hide_password=False), timeout=10)
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            cfg = Config(str(root / "alembic.ini"))
            cfg.set_main_option("script_location", str(root / "migrations"))
            assert await connection.fetchval("SELECT version_num FROM alembic_version") == ScriptDirectory.from_config(cfg).get_current_head()
            index = await connection.fetchval("SELECT indexdef FROM pg_indexes WHERE indexname='ix_agent_memories_cosine'")
            assert "hnsw" in index and "vector_cosine_ops" in index
            assert await connection.fetchval("SELECT to_regclass('agent_creator_affinity')")
            assert await connection.fetchval("SELECT to_regclass('data_sources')")
            assert await connection.fetchval("SELECT to_regclass('source_observations')")
        finally:
            await connection.close()
        test = '''
import asyncio
from app.db.session import session_scope, engine
from app.models import Organization, AgentMemory
from app.services.agent_memory import recall_many
from app.services.datapool.retrieval import embed
async def check():
    async with session_scope() as s:
        a, b = Organization(name="Memory A", slug="memory-a"), Organization(name="Memory B", slug="memory-b")
        s.add_all([a, b]); await s.flush()
        s.add(AgentMemory(org_id=a.id, population_ref="p:1", kind="opinion", text="I like simulated fitness content.",
            subject="topic:fitness", importance=.8, sentiment=.5, embedding=embed("fitness").tolist()))
        await s.flush()
        assert (await recall_many(s, a, ["p:1"], {"title": "fitness"}))["p:1"]
        assert (await recall_many(s, b, ["p:1"], {"title": "fitness"}))["p:1"] == []
    await engine.dispose()
asyncio.run(check())
'''
        result = await asyncio.to_thread(subprocess.run, [sys.executable, "-c", test], cwd=root, env=env, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError("PostgreSQL vector recall check failed; no server credentials are printed")
        print("PostgreSQL: previous head upgraded; HNSW vector index and tenant-isolated recall passed.")
    finally:
        if created and name.startswith("kruvim_memory_verify_"):
            await server.execute(f'DROP DATABASE "{name}" WITH (FORCE)')
        await server.close()


if __name__ == "__main__":
    if not os.environ.get("KRUVIM_MEMORY_TEST_PG_URL"):
        raise SystemExit("Set KRUVIM_MEMORY_TEST_PG_URL to a local PostgreSQL/pgvector test server URL.")
    asyncio.run(check())
