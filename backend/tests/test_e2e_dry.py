"""Full five-step workflow in dry-run mode: graph → environment → simulation → report → interaction,
plus tenancy, API keys, quotas, calibration and the data pool."""
import asyncio
import json

import pytest

SCRIPT = ("Stop paying for gym memberships you never use. Here is the 3 minute routine I do in my Dubai apartment every morning. "
          "First, 40 squats. No equipment, no excuses. Then 30 seconds of plank while the coffee brews. Most people quit because they think "
          "fitness needs an hour. It does not. Consistency beats intensity every single time. Follow for part two about Ramadan meals.")


async def wait_for(client, h, sim_id, field, values, timeout=240):
    for _ in range(timeout * 2):
        r = (await client.get(f"/simulations/{sim_id}", headers=h)).json()
        if r[field] in values:
            return r
        if r["status"] == "failed" and "failed" not in values:
            raise AssertionError(f"failed: {r['error']}")
        await asyncio.sleep(0.5)
    raise AssertionError(f"timeout waiting for {field} in {values}; last {r[field]} / {r.get('error')}")


@pytest.mark.asyncio
async def test_full_workflow(client, auth):
    h, session = auth
    assert session["user"]["is_superuser"] is True
    assert session["orgs"][0]["credits_balance"] > 0

    pr = (await client.post("/projects", json={"name": "Fitness launch", "description": "Q4 shorts"}, headers=h)).json()
    seed = await client.post(f"/projects/{pr['id']}/assets", headers=h, data={"kind": "seed"},
                             files={"file": ("brief.md", b"# Brief\nFitBox is a Dubai gym chain competing with GymNation. "
                                                         b"The campaign targets Emirati and expat professionals during Ramadan.", "text/markdown")})
    assert seed.status_code == 200, seed.text
    body = {"name": "Apartment workout v1", "requirement": "How will young Gulf professionals react, and what would make them share it?",
            "content": {"type": "video", "title": "3-minute apartment workout", "platform": "tiktok", "goal": "Grow followers",
                        "transcript": SCRIPT, "seed_asset_ids": [seed.json()["id"]],
                        "variant_b": {"title": "Results first", "transcript": "Day 30 results first. " + SCRIPT}},
            "audience": {"regions": ["AE", "SA"], "age_min": 18, "age_max": 44},
            "overrides": {"voice": 20, "crowd": 800, "stakeholders": 2, "hours": 4, "minutes_per_round": 60, "listening": False}}
    sim = (await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)).json()
    sid = sim["id"]

    # step 1
    assert (await client.post(f"/simulations/{sid}/graph", headers=h)).status_code == 200
    s1 = await wait_for(client, h, sid, "status", {"graph_ready"})
    assert s1["card"]["segments"] and s1["ontology"]["entity_types"]
    g = (await client.get(f"/simulations/{sid}/graph", headers=h)).json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"content", "region", "entity"} <= kinds and len(g["edges"]) > 5

    # step 2
    assert (await client.post(f"/simulations/{sid}/environment", headers=h)).status_code == 200
    s2 = await wait_for(client, h, sid, "status", {"ready"})
    assert s2["config"]["agents"]["voice"] == 20 and s2["config"]["time"]["rounds"] == 4
    agents = (await client.get(f"/simulations/{sid}/agents", headers=h)).json()
    assert any(a["kind"] == "stakeholder" for a in agents)
    r = await client.patch(f"/simulations/{sid}/config", headers=h,
                           json={"events": {"scheduled": [{"round": 2, "text": "A rival gym announces free Ramadan memberships"}]}})
    assert r.status_code == 200 and r.json()["config"]["events"]["scheduled"][0]["round"] == 2

    # step 3
    assert (await client.post(f"/simulations/{sid}/start", headers=h)).status_code == 200
    s3 = await wait_for(client, h, sid, "status", {"completed"})
    res = s3["results"]
    for key in ("score", "heatmap", "winners", "viral", "discourse", "timeline", "ab", "population_sample", "agents"):
        assert key in res, key
    assert len(res["timeline"]) == 5
    posts = (await client.get(f"/simulations/{sid}/posts?limit=1000", headers=h)).json()
    assert len(posts) >= 10  # 20 voice agents x 4 rounds; the exact count depends on the run seed
    assert any(p["kind"] == "event" for p in posts) and any(p["author_ref"] == "creator" for p in posts)
    ev = await client.get(f"/simulations/{sid}/events?after=0&follow=false", headers=h)
    types = {json.loads(line[6:])["type"] for line in ev.text.splitlines() if line.startswith("data: ")}
    assert {"graph.delta", "reaction", "round.end", "simulation.completed"} <= types

    # step 4
    s4 = await wait_for(client, h, sid, "report_status", {"done"})
    rep = (await client.get(f"/simulations/{sid}/report", headers=h)).json()
    assert rep["status"] == "done" and len(rep["sections"]) >= 3 and rep["log"]
    assert s4["step"] == 5

    # step 5
    voice = next(a for a in res["agents"] if a["kind"] == "voice")
    chat = (await client.post(f"/simulations/{sid}/agents/{voice['ref']}/chat", json={"message": "Why that score?"}, headers=h)).json()
    assert chat["reply"]
    any_pop = res["population_sample"]["rows"][0][0]
    d = (await client.get(f"/simulations/{sid}/agents/p:{int(any_pop)}", headers=h)).json()
    assert "projected" in d
    ex = (await client.post(f"/simulations/{sid}/explore", json={"regions": ["SA"], "genders": ["female"]}, headers=h)).json()
    assert ex["size"] > 0 and "retention" in ex
    sv = (await client.post(f"/simulations/{sid}/surveys", json={"question": "Would you follow this creator?", "n": 5}, headers=h)).json()
    assert sv["id"]
    for _ in range(60):
        rows = (await client.get(f"/simulations/{sid}/surveys", headers=h)).json()
        if rows[0]["status"] != "running":
            break
        await asyncio.sleep(0.5)
    assert rows[0]["status"] == "done" and len(rows[0]["answers"]) == 5
    rc = (await client.post(f"/simulations/{sid}/report/chat", json={"message": "Who should I target?"}, headers=h)).json()
    assert rc["answer"]

    # calibration, usage, audit, API keys
    assert (await client.post(f"/simulations/{sid}/performance", json={"platform": "tiktok", "views": 12000, "likes": 900}, headers=h)).status_code == 200
    usage = (await client.get("/usage", headers=h)).json()
    assert usage["credits_balance"] > 0 and usage["metered"] is False
    audit = (await client.get("/audit", headers=h)).json()
    assert any(a["action"] == "simulation.start" for a in audit)
    key = (await client.post("/api-keys", json={"name": "ci", "role": "viewer"}, headers=h)).json()["key"]
    lst = await client.get("/simulations", headers={"X-API-Key": key})
    assert lst.status_code == 200 and lst.json()[0]["id"] == sid
    denied = await client.post("/projects", json={"name": "x"}, headers={"X-API-Key": key})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_tenant_isolation(client, auth):
    h, _ = auth
    r = await client.post("/auth/register", json={"email": "other@example.com", "password": "another-long-password", "org_name": "Other"})
    h2 = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert r.json()["user"]["is_superuser"] is False
    mine = (await client.get("/projects", headers=h)).json()
    assert mine, "owner has projects"
    assert (await client.get(f"/projects/{mine[0]['id']}", headers=h2)).status_code == 404
    assert (await client.get("/projects", headers=h2)).json() == []


@pytest.mark.asyncio
async def test_validation_and_auth_errors(client):
    r = await client.post("/auth/register", json={"email": "bad", "password": "short"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert (await client.get("/projects")).status_code == 401
    assert (await client.post("/auth/login", json={"email": "owner@example.com", "password": "nope"})).status_code == 401
