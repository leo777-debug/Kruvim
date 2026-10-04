"""Disposable offline browser/API verification server; never opens the normal workspace database."""
import asyncio
import os
import tempfile

_directory = tempfile.mkdtemp(prefix="kruvim-browser-")
os.environ.update(KRUVIM_ENV="test", KRUVIM_DATA_DIR=_directory,
    KRUVIM_DATABASE_URL="sqlite+aiosqlite:///" + os.path.join(_directory, "verify.db").replace("\\", "/"),
    KRUVIM_REDIS_URL="", KRUVIM_POPULATION_SIZE="40000", KRUVIM_LLM_PROVIDER="dryrun", KRUVIM_LLM_PRESET="dryrun",
    KRUVIM_LLM_API_KEY="", KRUVIM_RATE_LIMIT_PER_MINUTE="10000")

from unittest.mock import AsyncMock  # noqa: E402

from sqlalchemy import update  # noqa: E402

from app.db.session import session_scope  # noqa: E402
from app.models import Connector  # noqa: E402
from app.services import datapool  # noqa: E402
from app.services.datapool import context, targeted  # noqa: E402
from scripts.seed_demo import main as seed  # noqa: E402


async def prepare():
    await seed()
    await datapool.ensure_platform_connectors()
    async with session_scope() as s:
        await s.execute(update(Connector).values(enabled=False))
    # Reproduce region-specific tone fallbacks without making external calls.
    import json
    from pathlib import Path

    from app.services.datapool.base import SignalItem
    from app.services.datapool.runner import store_signals
    fixture = json.loads((Path(__file__).parents[1] / "tests/fixtures/news_tone.json").read_text(encoding="utf-8"))
    await store_signals("google_news", [SignalItem("headline", code, title, payload={"source": "Recorded regional headlines"})
                                       for code, titles in fixture["headlines"].items() for title in titles])


if __name__ == "__main__":
    import uvicorn
    asyncio.run(prepare())
    datapool.run_due = AsyncMock(return_value=[])
    context.ensure_fresh = AsyncMock()
    targeted.prepare = AsyncMock()
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("KRUVIM_VERIFY_PORT", "8000")), access_log=False)
