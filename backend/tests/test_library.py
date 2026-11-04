import asyncio
import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.core.errors import AppError
from app.db.session import session_scope
from app.models.library import LibraryFolder
from app.services.library import evidence_block, inbox_path, parse_file, retrieve, sync_due


async def folder(client, headers, name="Research", project_id=None, **extra):
    response = await client.post("/library/folders", headers=headers,
        json={"name": name, "project_id": project_id, **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def row(client, headers, folder_id, **extra):
    response = await client.post(f"/library/folders/{folder_id}/entries", headers=headers,
        json={"title": "Coffee preferences", "data": "Customers prefer iced coffee", **extra})
    assert response.status_code == 200, response.text
    return response.json()


async def upload(client, headers, folder_id, raw, preview=False, mapping="{}"):
    return await client.post(f"/library/folders/{folder_id}/import", headers=headers,
        data={"preview": str(preview).lower(), "mapping": mapping}, files={"file": ("research.csv", raw)})


async def test_import_preview_mapping_replace_atomicity_and_manual_rows(client, auth):
    h, _ = auth
    f = await folder(client, h)
    await row(client, h, f["id"])
    raw = b"Topic,Finding\nCoffee,Cold drinks sell well\nTea,Evening demand\n"
    preview = await upload(client, h, f["id"], raw, True)
    assert preview.json()["rows"] == 2
    assert (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"] != []
    mapping = '{"title":"Topic","data":"Finding"}'
    assert (await upload(client, h, f["id"], raw, mapping=mapping)).status_code == 200
    assert (await upload(client, h, f["id"], raw, mapping=mapping)).json()["rows"] == 2
    rows = (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"]
    assert len(rows) == 3
    assert all(r["revision"] == 1 for r in rows)
    assert (await upload(client, h, f["id"], b"Topic,Finding\nCoffee,Updated finding\n", mapping=mapping)).status_code == 200
    rows = (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"]
    assert len(rows) == 2
    assert next(r for r in rows if r["filename"])["revision"] == 2
    assert (await upload(client, h, f["id"], b"title,data,region\nCoffee,Invalid,Atlantis\n")).status_code == 400
    assert (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"] == rows


async def test_customer_and_workspace_isolation_and_personal_retrieval(client, auth):
    h, session = auth
    project = (await client.post("/projects", headers=h, json={"name": "Customer A"})).json()
    other_project = (await client.post("/projects", headers=h, json={"name": "Customer B"})).json()
    private = await folder(client, h, project_id=project["id"])
    shared = await folder(client, h, name="Common")
    await row(client, h, private["id"], data="Private coffee research", region="AE-DXB", language="en")
    await row(client, h, shared["id"], title="Common coffee data")
    await row(client, h, shared["id"], title="Unrelated astronomy", data="Saturn has rings")
    personas = [{"region": "AE", "residence_emirate": "AE-DXB", "language": "English"},
                {"region": "AE", "residence_emirate": "AE-AUH", "language": "English"}]
    found = await retrieve(session["orgs"][0]["id"], project["id"], "coffee research", personas)
    assert len(found[0]) == 2 and len(found[1]) == 1
    assert "Private coffee research" in evidence_block(found[0])
    assert "unverified" in evidence_block(found[0])
    found = await retrieve(session["orgs"][0]["id"], other_project["id"], "coffee research", personas)
    assert all(len(items) == 1 and items[0]["folder_id"] == shared["id"] for items in found)
    other = (await client.post("/auth/register", json={"email": "other@example.com", "password": "correct-horse-battery",
        "name": "Other", "org_name": "Other workspace"})).json()
    other_h = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get(f"/library/folders/{private['id']}/entries", headers=other_h)).status_code == 404
    assert (await client.post("/library/folders", headers=other_h,
        json={"name": "Invalid", "project_id": project["id"]})).status_code == 404
    assert await retrieve(other["orgs"][0]["id"], project["id"], "coffee", personas) == [[], []]


async def test_watch_imports_changed_files_and_retains_good_data_on_failure(client, auth):
    h, _ = auth
    f = await folder(client, h, watch_enabled=True)
    async with session_scope() as s:
        root = inbox_path(await s.get(LibraryFolder, f["id"]))
    root.mkdir(parents=True)
    path = root / "weekly.csv"
    path.write_text("title,data\nCoffee,First survey\n", encoding="utf-8")
    await sync_due()
    await sync_due()
    saved = (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"]
    assert len(saved) == 1 and saved[0]["revision"] == 1
    path.write_text("title,data\nCoffee,Updated survey\n", encoding="utf-8")
    await sync_due()
    saved = (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"]
    assert saved[0]["revision"] == 2 and saved[0]["data"] == "Updated survey"
    path.write_text("title,data,region\nCoffee,Bad survey,Invalid\n", encoding="utf-8")
    await sync_due()
    assert (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"] == saved
    assert (await client.get("/library/folders", headers=h)).json()[0]["sync_status"]["errors"]


def test_xlsx_formula_rejection_and_generic_columns():
    book = Workbook()
    sheet = book.active
    sheet.append(["Product", "Price"])
    sheet.append(["Coffee", 20])
    raw = io.BytesIO()
    book.save(raw)
    assert parse_file("prices.xlsx", raw.getvalue())[1] == [{"Product": "Coffee", "Price": "20"}]
    sheet.cell(2, 2, "=10+10")
    raw = io.BytesIO()
    book.save(raw)
    with pytest.raises(AppError, match="formulas"):
        parse_file("prices.xlsx", raw.getvalue())
    with pytest.raises(AppError):
        parse_file("data.csv", b"title,title\na,b\n")


async def test_edits_delete_disabled_folder_and_immutable_evidence_copy(client, auth):
    h, session = auth
    f = await folder(client, h)
    r = await row(client, h, f["id"])
    people = [{"region": "AE", "language": "English"}]
    frozen = await retrieve(session["orgs"][0]["id"], None, "coffee", people)
    body = {k: r[k] for k in ("title", "data", "region", "language", "tags")}
    body["data"] = "New coffee finding"
    edited = await client.put(f"/library/folders/{f['id']}/entries/{r['id']}", headers=h, json=body)
    assert edited.json()["revision"] == 2
    assert frozen[0][0]["summary"] == "Customers prefer iced coffee"
    await client.put(f"/library/folders/{f['id']}", headers=h, json={"name": f["name"], "enabled": False})
    assert await retrieve(session["orgs"][0]["id"], None, "coffee", people) == [[]]
    assert (await client.delete(f"/library/folders/{f['id']}/entries/{r['id']}", headers=h)).status_code == 200
    assert (await client.get(f"/library/folders/{f['id']}/entries", headers=h)).json()["entries"] == []


async def test_simulation_preparation_freezes_project_evidence(client, auth):
    from sqlalchemy import select

    from app.models import SimAgent
    from app.services import jobs
    h, _ = auth
    project = (await client.post("/projects", headers=h, json={"name": "Cafe customer"})).json()
    f = await folder(client, h, project_id=project["id"])
    r = await row(client, h, f["id"], data="Synthetic research: customers prefer iced coffee in summer")
    created = await client.post(f"/projects/{project['id']}/simulations", headers=h, json={
        "name": "Coffee request", "requirement": "Evaluate coffee preferences",
        "content": {"format": "short_video", "type": "video", "platform": "tiktok", "title": "Coffee launch",
                    "text": "Try our summer iced coffee and tell us your favorite flavor."},
        "audience": {"regions": ["AE"]},
        "overrides": {"voice": 20, "crowd": 30, "stakeholders": 0, "hours": 1, "seed": 71, "listening": False}})
    assert created.status_code == 200, created.text
    sid = created.json()["id"]
    assert (await client.post(f"/simulations/{sid}/graph", headers=h)).status_code == 200
    await jobs.drain()
    assert (await client.post(f"/simulations/{sid}/environment", headers=h)).status_code == 200
    await jobs.drain()
    prepared = (await client.get(f"/simulations/{sid}", headers=h)).json()
    assert prepared["status"] == "ready", prepared.get("error")
    assert prepared["config"]["retrieval_usage"]["library_rows"] == 1
    await client.delete(f"/library/folders/{f['id']}/entries/{r['id']}", headers=h)
    async with session_scope() as s:
        agents = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sid, SimAgent.kind == "voice"))).scalars().all()
        assert agents
        for agent in agents:
            evidence = [e for e in agent.config["personal_signals"] if e["source"] == "workspace_library"]
            assert evidence[0]["id"] == "library:" + r["id"]
            assert "iced coffee" in evidence_block(evidence)


async def test_library_migration_upgrade_and_downgrade(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from app.core.config import settings
    db = tmp_path / "migration.db"
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///" + db.as_posix())
    root = Path(__file__).parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    await asyncio.to_thread(command.upgrade, cfg, "0015")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_engine("sqlite:///" + db.as_posix())
    try:
        assert {"library_folders", "library_entries"} <= set(inspect(engine).get_table_names())
        await asyncio.to_thread(command.downgrade, cfg, "0015")
        assert "library_folders" not in inspect(engine).get_table_names()
        await asyncio.to_thread(command.upgrade, cfg, "head")
    finally:
        engine.dispose()
