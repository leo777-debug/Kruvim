"""Source publication, licence gates and lossless native-grain imports (offline fixtures)."""
import asyncio
import io
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
from openpyxl import Workbook
from sqlalchemy import create_engine, inspect, select

from app.services.sources import eligible
from app.services.sources.adapters import Fetched, WorldBankAdapter, parse_table, table


async def make_super(auth, enabled=True):
    from app.db.session import session_scope
    from app.models import User
    async with session_scope() as s:
        user = (await s.execute(select(User).where(User.email == "owner@example.com"))).scalar_one()
        user.is_superuser = enabled


async def test_registry_crud_licence_and_private_upload(client, auth):
    headers = auth[0]
    sources = (await client.get("/datapool/sources", headers=headers)).json()
    assert len(sources) >= 29
    assert all(not x["production_eligible"] for x in sources)
    source = next(x for x in sources if x["key"] == "scad_statistics")
    await make_super(auth, False)
    assert (await client.patch(f"/datapool/sources/{source['id']}", headers=headers, json={"reliability": .8})).status_code == 403
    await make_super(auth)
    edit = await client.patch(f"/datapool/sources/{source['id']}", headers=headers,
        json={"reliability": .9, "licence_approved": True, "status": "active"})
    assert edit.status_code == 400  # No grant evidence.
    edit = await client.patch(f"/datapool/sources/{source['id']}", headers=headers,
        json={"reliability": .9, "licence_approved": True, "status": "active", "approval_note": "Recorded test grant, fixture only"})
    assert edit.status_code == 200, edit.text
    assert edit.json()["production_eligible"]
    assert (await client.patch(f"/datapool/sources/{source['id']}", headers=headers, json={"reliability": 2})).status_code == 422
    # Synthetic fixture numbers, never registered as factual production observations.
    raw = b"Year,Sex,Amount\n2023,female,40\n2023,male,60\n2024,female,..\n"
    upload = await client.post("/datapool/datasets", headers=headers, files={"file": ("fixture.csv", raw)},
                              data={"registered_source_id": source["id"]})
    assert upload.status_code == 200, upload.text
    dataset = upload.json()["id"]
    mapping = {"value_col": "Amount", "period_col": "Year", "period_format": "year", "metric": "population_share",
               "unit": "percent", "geography": "AE-AUH", "dimensions": {"sex": "Sex"}}
    preview = await client.put(f"/datapool/datasets/{dataset}/mapping", headers=headers, json=mapping)
    assert preview.status_code == 200, preview.text
    assert preview.json()["summary"]["observations"] == 2
    assert preview.json()["summary"]["missing_cells"] == 1
    applied = await client.post(f"/datapool/datasets/{dataset}/apply", headers=headers)
    assert applied.status_code == 200, applied.text
    assert applied.json()["observations"] == 2
    assert (await client.post(f"/datapool/datasets/{dataset}/apply", headers=headers)).json()["observations"] == 0
    observations = (await client.get(f"/datapool/sources/{source['id']}/observations", headers=headers)).json()
    assert sorted(o["value"] for o in observations) == [40, 60]
    assert all(o["raw_ref"] == "asset:" + dataset and o["period_start"].startswith("2023-01-01") for o in observations)
    from app.db.session import session_scope
    from app.models import Dataset
    from app.services import storage
    async with session_scope() as s:
        record = await s.get(Dataset, dataset)
        assert await storage.get(record.storage_key) == raw
    other = (await client.post("/auth/register", json={"email": "other@example.com", "password": "correct-horse-battery", "name": "Other", "org_name": "Other"})).json()
    other_headers = {"Authorization": "Bearer " + other["access_token"]}
    assert (await client.get("/datapool/datasets", headers=other_headers)).json() == []
    assert (await client.put(f"/datapool/datasets/{dataset}/mapping", headers=other_headers, json=mapping)).status_code == 404
    assert len((await client.get(f"/datapool/sources/{source['id']}/observations", headers=other_headers)).json()) == 2
    assert (await client.patch(f"/datapool/sources/{source['id']}", headers=headers, json={"licence": "Changed licence"})).json()["production_eligible"] is False
    assert (await client.delete(f"/datapool/sources/{source['id']}", headers=headers)).json()["status"] == "deprecated"
    assert len((await client.get(f"/datapool/sources/{source['id']}/observations", headers=headers)).json()) == 2


def test_native_xlsx_periods_and_formula_rejection():
    wb = Workbook()
    ws = wb.active
    ws.append(["Period", "Amount", "Area"])
    ws.append(["2024-02", 7, "SHJ"])
    ws.append(["2024-03", None, "SHJ"])
    out = io.BytesIO()
    wb.save(out)
    mapping = {"value_col": "Amount", "period_col": "Period", "period_format": "month", "metric": "fixture",
               "unit": "count", "geography": "AE-SHJ", "dimensions": {"emirate": "Area"}}
    rows, missing = parse_table(out.getvalue(), mapping, "fixture.xlsx")
    assert missing == 1 and rows[0]["value"] == 7
    assert rows[0]["period_end"].day == 29 and rows[0]["dimensions"] == {"emirate": "SHJ"}
    ws.append(["2024-04", "=1+1", "SHJ"])
    out = io.BytesIO()
    wb.save(out)
    import pytest
    with pytest.raises(ValueError, match="formula"):
        table(out.getvalue(), "fixture.xlsx")
    with pytest.raises(ValueError, match="dimension cell is missing"):
        parse_table(b"Period,Amount,Area\n2024-02,7,\n", mapping)


def test_worldbank_adapter_retains_year_and_missing_values():
    adapter = WorldBankAdapter()
    source = SimpleNamespace(country="AE", config={"metric": "financial_access", "unit": "percent"})
    file = Fetched(b'[{"pages":1},[{"date":"2021","value":42,"indicator":{"id":"fixture"}},'
                   b'{"date":"2022","value":null,"indicator":{"id":"fixture"}}]]', "fixture.json", "https://example.com")
    rows, missing = adapter.parse(file, source)
    assert missing == 1 and rows[0]["value"] == 42 and rows[0]["period_start"].year == 2021
    assert not eligible(SimpleNamespace(status="active", licence_approved=False, reliability=1))


async def test_source_registry_migration_from_previous_head(tmp_path, monkeypatch):
    from app.core.config import settings
    root = Path(__file__).parents[1]
    db = tmp_path / "registry.db"
    monkeypatch.setattr(settings, "database_url", "sqlite+aiosqlite:///" + db.as_posix())
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    await asyncio.to_thread(command.upgrade, cfg, "0007")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    engine = create_engine("sqlite:///" + db.as_posix())
    try:
        assert {"data_sources", "source_observations"} <= set(inspect(engine).get_table_names())
        assert "source_id" in {x["name"] for x in inspect(engine).get_columns("signals")}
        assert "coverage_gaps" in {x["name"] for x in inspect(engine).get_columns("population_versions")}
        await asyncio.to_thread(command.downgrade, cfg, "0007")
        assert "data_sources" not in inspect(engine).get_table_names()
    finally:
        engine.dispose()
