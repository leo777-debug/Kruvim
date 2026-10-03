"""Alembic environment (async). The database URL comes from KRUVIM_DATABASE_URL via app settings."""
import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.base import UTCDateTime
from app.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    return not (settings.is_sqlite and type_ == "index" and name == "ix_signal_embeddings_cosine")


def render_item(type_, obj, autogen_context):
    """Migrations stay free of app imports: UTCDateTime is a plain timezone-aware DateTime in the database."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True,
                      render_as_batch=settings.is_sqlite, compare_type=True, render_item=render_item, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


def do_run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=settings.is_sqlite, compare_type=True,
                      render_item=render_item, include_object=include_object)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online():
    engine = async_engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
