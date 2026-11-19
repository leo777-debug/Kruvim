import copy

import pytest
from sqlalchemy import text

from app.db.session import engine
from tools.verify_recovery import compare, snapshot


@pytest.fixture
async def revision(client):
    # The API fixture builds metadata directly, without Alembic.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num TEXT NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version VALUES ('fixture')"))
    try:
        yield
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE alembic_version"))


async def test_recovery_detects_missing_rows_missing_objects_and_same_size_corruption(client, auth, revision):
    from app.services import storage

    headers, _ = auth
    project = (await client.post("/projects", headers=headers, json={"name": "Recovery fixture"})).json()
    extracted = await client.post(f"/projects/{project['id']}/assets/extracted-text", headers=headers,
                                  json={"filename": "local.pdf", "text": "Extracted locally"})
    assert extracted.status_code == 200
    response = await client.post(f"/projects/{project['id']}/assets", headers=headers,
                                files={"file": ("fixture.txt", b"original", "text/plain")})
    assert response.status_code == 200
    before = await snapshot()
    assert extracted.json()["id"] in before["database_assets"]
    compare(before, await snapshot())
    asset = before["assets"][response.json()["id"]]
    await storage.put(asset["key"], b"modified")  # identical byte count, different content
    with pytest.raises(ValueError, match="assets"):
        compare(before, await snapshot())
    await storage.put(asset["key"], b"original")
    compare(before, await snapshot())
    await storage.delete(asset["key"])
    with pytest.raises(FileNotFoundError):
        await snapshot()
    changed = copy.deepcopy(before)
    changed["tables"]["assets"] -= 1
    with pytest.raises(ValueError, match="tables"):
        compare(before, changed)
    changed = copy.deepcopy(before)
    changed["revision"] = ["wrong-revision"]
    with pytest.raises(ValueError, match="revision"):
        compare(before, changed)
