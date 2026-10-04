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
