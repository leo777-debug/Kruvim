"""Disposable local browser trial with real public feeds and a browser-entered model key."""
import asyncio
import os
import secrets
import tempfile

trial_directory = tempfile.mkdtemp(prefix="kruvim-mistral-trial-")
os.environ.update(
    KRUVIM_ENV="test", KRUVIM_DATA_DIR=trial_directory,
    KRUVIM_DATABASE_URL="sqlite+aiosqlite:///" + os.path.join(trial_directory, "trial.db").replace("\\", "/"),
    KRUVIM_DATABASE_SCHEMA="", KRUVIM_SERVERLESS="false", KRUVIM_STORAGE_BACKEND="local", KRUVIM_REDIS_URL="",
    KRUVIM_SECRET_KEY=secrets.token_urlsafe(48), KRUVIM_POPULATION_SIZE="40000",
    KRUVIM_LLM_PROVIDER="dryrun", KRUVIM_LLM_PRESET="dryrun", KRUVIM_LLM_API_KEY="",
    KRUVIM_BILLING_ENABLED="false", KRUVIM_RATE_LIMIT_PER_MINUTE="10000",
    KRUVIM_FIRST_SUPERUSER_EMAIL="", KRUVIM_FIRST_SUPERUSER_PASSWORD="",
)

from sqlalchemy import update  # noqa: E402

from app.db.session import engine, session_scope  # noqa: E402
from app.models import Connector  # noqa: E402
from app.services.datapool.context import refresh_snapshot_archive  # noqa: E402
from app.services.datapool.runner import refresh_free_feeds  # noqa: E402
from scripts.seed_demo import main as seed  # noqa: E402


async def prepare():
    await seed()
    from app.services.datapool.runner import ensure_platform_connectors
    await ensure_platform_connectors()
    async with session_scope() as session:
        await session.execute(update(Connector).values(enabled=False))
        await session.execute(update(Connector).where(Connector.key.in_(
            ["gdelt_events", "usgs_earthquakes", "nasa_eonet", "wikipedia"])).values(enabled=True))
    results = await refresh_free_feeds()
    print("Public feed checks:", [{"source": item["key"], "status": item["status"], "items": item["items"]} for item in results], flush=True)
    print("Archived regional snapshots:", await refresh_snapshot_archive(), flush=True)
    await engine.dispose()


if __name__ == "__main__":
    import uvicorn
    asyncio.run(prepare())
    uvicorn.run("app.main:app", host="127.0.0.1", port=8037, access_log=False)
