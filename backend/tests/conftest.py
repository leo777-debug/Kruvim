import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="kruvim-test-")
# Table resets must never touch an inherited application/production database.
# Provider protocol tests explicitly connect their own stub after this setup.
os.environ.update(KRUVIM_ENV="test", KRUVIM_DATA_DIR=_tmp,
    KRUVIM_DATABASE_URL="sqlite+aiosqlite:///" + os.path.join(_tmp, "test.db").replace("\\", "/"),
    KRUVIM_POPULATION_SIZE="40000", KRUVIM_REDIS_URL="", KRUVIM_RATE_LIMIT_AUTH_PER_MINUTE="1000",
    KRUVIM_LLM_PROVIDER="dryrun", KRUVIM_LLM_PRESET="dryrun", KRUVIM_LLM_API_KEY="",
    KRUVIM_FIRST_SUPERUSER_EMAIL="", KRUVIM_FIRST_SUPERUSER_PASSWORD="")


import httpx  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
async def isolated_state(monkeypatch, tmp_path):
    """No workspace, queue, event, rate-limit or disk state survives another test."""
    from app.core import ratelimit
    from app.core.config import settings
    from app.db.session import engine
    from app.models import Base
    from app.services import jobs, lifecycle
    from app.services.events import bus
    from app.services.population import store

    await jobs.drain()
    saved = settings.model_copy(deep=True)
    monkeypatch.setattr(settings, "data_dir", str(tmp_path / "data"))
    for cache in (ratelimit._local, jobs._local_ctl, lifecycle._start_locks, bus._seq, bus._locks, bus._local, store._cache):
        cache.clear()
    jobs._local_sem = None
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    try:
        yield
    finally:
        # Finish chained jobs before patches disappear or the next test resets tables.
        await jobs.drain()
        for name in type(settings).model_fields:
            setattr(settings, name, getattr(saved, name))


@pytest.fixture
async def client(isolated_state):
    # External feeds have their own integration checks. Keep the application suite
    # reproducible and offline; network timeouts otherwise stall every graph build.
    from unittest.mock import AsyncMock, patch

    from app.main import app
    with patch("app.services.datapool.run_due", new=AsyncMock(return_value=[])), \
         patch("app.services.datapool.targeted.prepare", new=AsyncMock()), \
         patch("app.services.datapool.context.ensure_fresh", new=AsyncMock()):
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test/api/v1", timeout=60) as c:
                try:
                    yield c
                finally:
                    from app.services import jobs
                    await jobs.drain()


@pytest.fixture
async def auth(client):
    r = await client.post("/auth/register", json={"email": "owner@example.com", "password": "correct-horse-battery", "name": "Owner",
                                                  "org_name": "Acme Media"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data
