"""Run Alembic migrations from inside the app (used for local SQLite databases so they never drift from the models)."""
from __future__ import annotations

import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.core.config import settings

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def upgrade_head() -> None:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "migrations"))
    sync_url = settings.database_url.replace("+aiosqlite", "").replace("+asyncpg", "+psycopg") if settings.is_sqlite else None
    if sync_url:
        eng = create_engine(sync_url)
        try:
            tables = set(inspect(eng).get_table_names())
        finally:
            eng.dispose()
        if "simulations" in tables and "alembic_version" not in tables:
            from app.models import Base
            command.stamp(cfg, "head" if set(Base.metadata.tables).issubset(tables) else "0001")
    command.upgrade(cfg, "head")
