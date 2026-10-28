"""Workspace isolation, swept over every route: another workspace's ids must never be readable or changeable.

Workspace A builds real data (a completed dry-run simulation with its report, share link, survey, assets,
dataset, template, annotation, watch, invite and API key). Workspace B then calls every route that takes an id
with A's ids substituted, using every method the route supports, and must get "not found" or "forbidden"
(or a validation error before any lookup). B's list endpoints must not mention any of A's ids either."""
from __future__ import annotations

import re

from tests.test_e2e_dry import SCRIPT, wait_for

ALLOWED = {401, 403, 404, 405, 422, 429}

# Routes that take a parameter but are not workspace data, each with the reason.
SHARED_BY_DESIGN = {
    "/shared-results/{token}": "public share links are authorised by their secret token",
    "/social/{platform}/callback": "OAuth callback, authorised by a single-use state token",
    "/social/{platform}/connect": "platform name, not an id",
    "/datapool/population/agents/{idx}": "the synthetic population is shared reference data",
    "/datapool/sources/{source_id}/observations": "the statistical source registry is shared reference data",
}


async def _workspace_a(client, h):
    pr = (await client.post("/projects", json={"name": "A private project"}, headers=h)).json()
    seed = (await client.post(f"/projects/{pr['id']}/assets", headers=h, data={"kind": "seed"},
                              files={"file": ("brief.md", b"# Private brief\nConfidential launch plan.", "text/markdown")})).json()
    body = {"name": "A private test", "requirement": "How will people react?",
            "content": {"type": "video", "title": "Private", "platform": "tiktok", "transcript": SCRIPT, "seed_asset_ids": [seed["id"]]},
            "audience": {"regions": ["AE"]},
            "overrides": {"voice": 10, "crowd": 500, "stakeholders": 1, "hours": 2, "minutes_per_round": 60, "listening": False}}
    r = await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)
    assert r.status_code == 200, r.text
    sid = r.json()["id"]
    await client.post(f"/simulations/{sid}/graph", headers=h)
    await wait_for(client, h, sid, "status", {"graph_ready"})
    await client.post(f"/simulations/{sid}/environment", headers=h)
    await wait_for(client, h, sid, "status", {"ready"})
    await client.post(f"/simulations/{sid}/start", headers=h)
    await wait_for(client, h, sid, "report_status", {"done"})
    agents = (await client.get(f"/simulations/{sid}/agents", headers=h)).json()
    share = (await client.post(f"/simulations/{sid}/shares", headers=h, json={"days": 1})).json()
    ann = (await client.post(f"/simulations/{sid}/annotations", headers=h, json={"text": "private note", "target": "report"})).json()
    tpl = (await client.post("/audience-templates", headers=h, json={"name": "Private audience", "audience": {"regions": ["AE"]}})).json()
    key = (await client.post("/api-keys", headers=h, json={"name": "A key"})).json()
    inv = (await client.post("/members/invites", headers=h, json={"email": "a-guest@example.com"})).json()
    members = (await client.get("/members", headers=h)).json()
    dataset = (await client.post("/datapool/datasets", headers=h, data={"name": "A data"},
                                 files={"file": ("a.csv", b"country,value\nAE,1\n", "text/csv")})).json()
    watch = (await client.post("/watches", headers=h, json={"project_id": pr["id"], "feed_url": "https://example.com/feed.xml",
                                                            "name": "A watch"}))
    ids = {"project_id": pr["id"], "sim_id": sid, "asset_id": seed["id"], "ref": agents[0]["ref"], "share_id": share.get("id"),
           "ann_id": ann.get("id"), "tpl_id": tpl.get("id"), "key_id": key.get("id"), "invite_id": inv.get("id"),
           "member_id": members["members"][0]["id"], "dataset_id": dataset.get("id"), "org_id": None,
           "watch_id": watch.json().get("id") if watch.status_code == 200 else None}
    return {k: v for k, v in ids.items() if v}


async def test_no_route_exposes_another_workspaces_data(client, auth):
    from app.main import app
    ha, session_a = auth
    ids = await _workspace_a(client, ha)
    ids["org_id"] = session_a["orgs"][0]["id"]

    r = await client.post("/auth/register", json={"email": "other@example.com", "password": "another-password-1", "org_name": "B"})
    hb = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert r.json()["user"]["is_superuser"] is False

    leaks, checked = [], 0
    for path, ops in app.openapi()["paths"].items():
        route = path.removeprefix("/api/v1")
        params = re.findall(r"{(\w+)}", route)
        if not params or route in SHARED_BY_DESIGN:
            continue
        url = route
        for name in params:
            url = url.replace("{" + name + "}", str(ids.get(name, "0" * 32)))
        for method in ops:
            kw = {"json": {}} if method in ("post", "put", "patch") else {}
            resp = await client.request(method.upper(), url, headers=hb, **kw)
            checked += 1
            if resp.status_code not in ALLOWED:
                leaks.append(f"{method.upper()} {route} -> {resp.status_code}: {resp.text[:160]}")
    assert checked >= 80
    assert not leaks, "Cross-workspace access:\n" + "\n".join(leaks)

    # A's data still exists and B's own lists never mention it.
    assert (await client.get(f"/simulations/{ids['sim_id']}", headers=ha)).status_code == 200
    private = {v for k, v in ids.items() if k not in ("member_id",)}
    for path, ops in app.openapi()["paths"].items():
        route = path.removeprefix("/api/v1")
        if "{" in route or "get" not in ops or route.startswith(("/admin", "/auth")) or route.endswith("/events"):
            continue
        text = (await client.get(route, headers=hb)).text
        assert not [v for v in private if v in text], f"GET {route} lists another workspace's ids"
