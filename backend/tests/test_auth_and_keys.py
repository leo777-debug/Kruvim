"""Critical paths: sessions (login, refresh rotation, logout, password change) and stored model-provider keys."""
from __future__ import annotations

import logging

PASSWORD = "correct-horse-battery"
SECRET = "sk-test-0123456789abcdefSECRET"


async def test_login_does_not_reveal_which_emails_exist(client, auth):
    unknown = await client.post("/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    wrong = await client.post("/auth/login", json={"email": "owner@example.com", "password": "wrong-password-1"})
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]


async def test_refresh_rotation_and_reuse_detection(client, auth):
    _, session = auth
    first = session["refresh_token"]
    r = await client.post("/auth/refresh", json={"refresh_token": first})
    assert r.status_code == 200
    second = r.json()["refresh_token"]
    assert second != first
    # Replaying a rotated token looks like theft: every session of that user is revoked.
    assert (await client.post("/auth/refresh", json={"refresh_token": first})).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": second})).status_code == 401


async def test_logout_and_password_change_end_sessions(client, auth):
    h, session = auth
    other = (await client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})).json()["refresh_token"]
    assert (await client.post("/auth/logout", json={"refresh_token": session["refresh_token"]})).status_code == 200
    assert (await client.post("/auth/refresh", json={"refresh_token": session["refresh_token"]})).status_code == 401

    r = await client.post("/auth/password", headers=h, json={"current_password": "wrong-password-1", "new_password": "a-new-password-2"})
    assert r.status_code == 401
    r = await client.post("/auth/password", headers=h, json={"current_password": PASSWORD, "new_password": "a-new-password-2"})
    assert r.status_code == 200
    assert (await client.post("/auth/refresh", json={"refresh_token": other})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "owner@example.com", "password": PASSWORD})).status_code == 401
    assert (await client.post("/auth/login", json={"email": "owner@example.com", "password": "a-new-password-2"})).status_code == 200


async def test_requests_without_a_valid_session_are_refused(client, auth):
    for headers in ({}, {"Authorization": "Bearer not-a-jwt"}, {"Authorization": "Bearer krv_not-a-real-key"}):
        r = await client.get("/projects", headers=headers)
        assert r.status_code == 401, (headers, r.text)


async def test_provider_key_is_encrypted_masked_and_never_logged(client, auth, caplog, accept_keys):
    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models import ProviderConfig, ProviderKey
    h, _ = auth
    caplog.set_level(logging.DEBUG)
    r = await client.put("/providers", headers=h, json={"preset": "openai", "api_key": SECRET, "voice_model": "gpt-x"})
    assert r.status_code == 200
    for response in (r, await client.get("/providers", headers=h), await client.get("/usage", headers=h)):
        assert SECRET not in response.text
    assert r.json()["api_key_hint"].endswith(SECRET[-4:]) and r.json()["api_key_set"] is True

    async with session_scope() as s:
        stored = (await s.execute(select(ProviderKey))).scalar_one().api_key_enc
        assert (await s.execute(select(ProviderConfig))).scalar_one().api_key_enc is None   # only the vault holds it
    assert stored and SECRET not in stored

    # Saving without a key keeps the stored one; an empty string clears it.
    assert (await client.put("/providers", headers=h, json={"preset": "openai", "voice_model": "gpt-y"})).json()["api_key_set"]
    assert not (await client.put("/providers", headers=h, json={"preset": "openai", "api_key": ""})).json()["api_key_set"]
    assert SECRET not in caplog.text


async def test_only_admins_change_provider_keys(client, auth, accept_keys):
    h, _ = auth
    inv = (await client.post("/members/invites", headers=h, json={"email": "member@example.com", "role": "member"})).json()
    token = inv["accept_url"].rsplit("/", 1)[-1]
    member = (await client.post("/auth/invites/accept", json={"token": token, "password": "member-password-1"})).json()
    mh = {"Authorization": f"Bearer {member['access_token']}"}
    assert (await client.put("/providers", headers=mh, json={"preset": "openai", "api_key": SECRET})).status_code == 403
    assert (await client.delete("/providers", headers=mh)).status_code == 403
    assert (await client.post("/providers/test", headers=mh, json={"preset": "dryrun"})).status_code == 403


async def test_workspace_api_keys_are_shown_once_and_can_be_revoked(client, auth):
    h, _ = auth
    created = (await client.post("/api-keys", headers=h, json={"name": "orchestrator"})).json()
    raw = created["key"]
    listed = (await client.get("/api-keys", headers=h)).text
    assert raw not in listed and created["prefix"] in listed
    assert (await client.get("/projects", headers={"X-API-Key": raw})).status_code == 200
    assert (await client.delete(f"/api-keys/{created['id']}", headers=h)).status_code == 200
    assert (await client.get("/projects", headers={"X-API-Key": raw})).status_code == 401


async def test_user_can_stop_a_running_simulation(client, auth):
    from app.services import jobs
    from tests.test_e2e_dry import SCRIPT, wait_for
    h, _ = auth
    pr = (await client.post("/projects", json={"name": "Stop me"}, headers=h)).json()
    body = {"name": "Long run", "requirement": "How will people react?",
            "content": {"type": "video", "title": "Long", "platform": "tiktok", "transcript": SCRIPT}, "audience": {"regions": ["AE"]},
            "overrides": {"voice": 10, "crowd": 500, "stakeholders": 1, "hours": 24, "minutes_per_round": 60, "listening": False}}
    sid = (await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)).json()["id"]
    await client.post(f"/simulations/{sid}/graph", headers=h)
    await wait_for(client, h, sid, "status", {"graph_ready"})
    await client.post(f"/simulations/{sid}/environment", headers=h)
    await wait_for(client, h, sid, "status", {"ready"})

    assert (await client.post(f"/simulations/{sid}/start", headers=h)).status_code == 200
    r = await client.post(f"/simulations/{sid}/control", headers=h, json={"cmd": "stop"})
    assert r.status_code == 200, r.text
    await jobs.drain()
    sim = (await client.get(f"/simulations/{sid}", headers=h)).json()
    assert sim["status"] in ("completed", "cancelled"), sim.get("error")
    assert sim["results"].get("stopped_early") is True
    assert len(sim["results"].get("timeline") or []) < 25          # it did not run all 24 rounds
    # A finished run cannot be controlled any more.
    assert (await client.post(f"/simulations/{sid}/control", headers=h, json={"cmd": "pause"})).status_code == 409
