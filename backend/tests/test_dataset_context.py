from app.services.dataset_context import compact_selection, numeric_fields, prepare_candidates


def test_numeric_cells_do_not_guess_numbers_in_prose_or_identifiers():
    from decimal import Decimal
    assert numeric_fields('{"amount": 9007199254740993.01}')["amount"] == Decimal("9007199254740993.01")
    assert numeric_fields('Customers aged 20 prefer coffee') == {}
    assert numeric_fields('{"age": 20, "active": true, "customer_id": 123}') == {"age": 20}
    assert numeric_fields('age: 20; amount: -3.5; postal code: 12345; rate: 10%') == {"age": 20, "amount": -3.5}


def test_statistics_are_exact_scoped_bounded_and_revisioned():
    def evidence(id, data, file="a", region="AE", revision=1):
        return (1, "own", {"id": id, "folder_id": "f", "dataset_file_id": file,
            "region": region, "language": "en", "summary": data, "revision": revision})
    rows = [evidence("1", "age: 20; income: 100"), evidence("2", "age: 40; income: 300"),
            evidence("3", "age: 90", file="b"), evidence("4", "age: 80", region="US")]
    assert prepare_candidates(rows) == 3
    a = rows[0][2]["dataset_statistics"]
    assert a["rows"] == 2
    assert a["numeric_fields"]["age"] == {"count": 2, "sum": "60", "mean": "3E+1", "min": "20", "max": "40"}
    assert rows[2][2]["dataset_statistics"]["rows"] == 1
    assert len(rows[0][2]["summary"]) <= 1200
    packed = compact_selection([rows[0][2], rows[1][2]])
    assert "Code-calculated" in packed[0]["summary"]
    assert packed[1]["summary"] == "age: 40; income: 300"
    assert "dataset_statistics" not in packed[1]
    assert "dataset_statistics" in rows[1][2]
    old = a["revision_digest"]
    changed = [evidence("1", "age: 20; income: 100", revision=2), evidence("2", "age: 40; income: 300")]
    prepare_candidates(changed)
    assert changed[0][2]["dataset_statistics"]["revision_digest"] != old


async def test_library_prepares_once_and_reuses_selection(client, auth, monkeypatch):
    from app.services import library
    from app.services.datapool import retrieval
    h, session = auth
    f = (await client.post("/library/folders", headers=h, json={"name": "Research"})).json()
    for age, purchases in [(20, 2), (40, 4)]:
        r = await client.post(f"/library/folders/{f['id']}/entries", headers=h,
            json={"title": "Coffee survey", "data": f"age: {age}; purchases: {purchases}"})
        assert r.status_code == 200
    calls = 0
    original = retrieval.personal_match
    def counted(*args):
        nonlocal calls
        calls += 1
        return original(*args)
    monkeypatch.setattr(retrieval, "personal_match", counted)
    people = [{"region": "AE", "language": "English", "name": str(i)} for i in range(100)]
    found = await library.retrieve(session["orgs"][0]["id"], None, "Coffee", people)
    assert calls == 2
    assert len(found) == 100
    assert found[0] == found[-1] and found[0] is not found[-1]
    assert found[0][0]["dataset_statistics"]["numeric_fields"]["purchases"]["sum"] == "6"
    assert "Code-calculated" in library.evidence_block(found[0])
    fresh = await library.retrieve(session["orgs"][0]["id"], None, "unrelated astronomy", people)
    assert all(not items for items in fresh)


async def test_uploaded_dataset_survives_preparation_and_run(client, auth):
    from sqlalchemy import select
    from app.db.session import session_scope
    from app.models import SimAgent
    from app.services import jobs
    from app.services.library import evidence_block
    h, _ = auth
    project = (await client.post("/projects", headers=h, json={"name": "Shared dataset verification"})).json()
    folder = (await client.post("/library/folders", headers=h,
        json={"name": "Coffee research", "project_id": project["id"]})).json()
    uploaded = await client.post(f"/library/folders/{folder['id']}/import", headers=h,
        data={"preview": "false"}, files={"file": ("coffee.csv", b"title,age,purchases\nCoffee,20,2\nCoffee,40,4\n")})
    assert uploaded.status_code == 200, uploaded.text
    created = await client.post(f"/projects/{project['id']}/simulations", headers=h, json={
        "name": "Coffee launch", "requirement": "Evaluate coffee preferences",
        "content": {"type": "video", "platform": "tiktok", "title": "Coffee launch", "text": "Try our iced coffee."},
        "audience": {"regions": ["AE"]},
        "overrides": {"voice": 20, "crowd": 30, "stakeholders": 0, "hours": 1, "listening": False}})
    assert created.status_code == 200, created.text
    sid = created.json()["id"]
    for step, status in [("graph", "graph_ready"), ("environment", "ready")]:
        response = await client.post(f"/simulations/{sid}/{step}", headers=h)
        assert response.status_code == 200, response.text
        await jobs.drain()
        sim = (await client.get(f"/simulations/{sid}", headers=h)).json()
        assert sim["status"] == status, sim.get("error")
    async with session_scope() as s:
        agents = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sid, SimAgent.kind == "voice"))).scalars().all()
        assert len(agents) == 20
        for agent in agents:
            selected = [e for e in agent.config["personal_signals"] if e["source"] == "workspace_library"]
            summaries = [e["dataset_statistics"] for e in selected if "dataset_statistics" in e]
            assert len(summaries) == 1
            assert summaries[0]["numeric_fields"]["purchases"]["sum"] == "6"
            assert evidence_block(selected).count("Code-calculated dataset statistics:") == 1
    # Live library changes do not rewrite the frozen evidence of a prepared run.
    await client.put(f"/library/folders/{folder['id']}", headers=h,
        json={"name": "Coffee research", "project_id": project["id"], "enabled": False})
    started = await client.post(f"/simulations/{sid}/start", headers=h)
    assert started.status_code == 200, started.text
    await jobs.drain()
    finished = (await client.get(f"/simulations/{sid}", headers=h)).json()
    assert finished["status"] == "completed", finished.get("error")
    assert finished["report_status"] == "done", finished.get("error")
