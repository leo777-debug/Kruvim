import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="kruvim-test-")
os.environ.setdefault("KRUVIM_ENV", "test")
os.environ.setdefault("KRUVIM_DATA_DIR", _tmp)
os.environ.setdefault("KRUVIM_DATABASE_URL", "sqlite+aiosqlite:///" + os.path.join(_tmp, "test.db").replace("\\", "/"))
os.environ.setdefault("KRUVIM_POPULATION_SIZE", "40000")
os.environ.setdefault("KRUVIM_REDIS_URL", "")
os.environ.setdefault("KRUVIM_RATE_LIMIT_AUTH_PER_MINUTE", "1000")


import httpx  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(scope="session")
async def client():
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
                yield c


@pytest.fixture(scope="session")
async def auth(client):
    r = await client.post("/auth/register", json={"email": "owner@example.com", "password": "correct-horse-battery", "name": "Owner",
                                                  "org_name": "Acme Media"})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data
