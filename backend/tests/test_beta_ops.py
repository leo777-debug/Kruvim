"""Beta operations: invite-only sign-up, the platform admin views and error monitoring."""
from __future__ import annotations

import pytest

PASSWORD = "beta-password-123"


async def _signup(client, email, code=None):
    body = {"email": email, "password": PASSWORD, **({"invite_code": code} if code else {})}
    return await client.post("/auth/register", json=body)


@pytest.fixture
def invite_only(monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "allow_registration", False)


async def test_invite_codes_gate_sign_up(client, auth, invite_only):
    h, _ = auth                                       # the first account is the platform admin in tests
    assert (await _signup(client, "nobody@example.com")).json()["error"]["code"] == "registration_closed"
    assert (await _signup(client, "nobody@example.com", "KRV-WRONG")).json()["error"]["code"] == "invite_invalid"

    made = (await client.post("/admin/beta-invites", headers=h, json={"note": "Creator cohort", "max_uses": 2})).json()
    code = made["code"]
    assert made["signup_url"].endswith(f"/register?code={code}")
    assert code not in (await client.get("/admin/beta-invites", headers=h)).text       # shown once, only the hash is kept
    assert (await _signup(client, "one@example.com", code)).status_code == 200
    assert (await _signup(client, "two@example.com", f"  {code} ")).status_code == 200
    assert (await _signup(client, "three@example.com", code)).json()["error"]["code"] == "invite_used"

    personal = (await client.post("/admin/beta-invites", headers=h, json={"email": "vip@example.com"})).json()
    assert (await _signup(client, "someone-else@example.com", personal["code"])).json()["error"]["code"] == "invite_invalid"
    await client.delete(f"/admin/beta-invites/{personal['id']}", headers=h)
    assert (await _signup(client, "vip@example.com", personal["code"])).json()["error"]["code"] == "invite_invalid"
    states = {i["id"]: i["state"] for i in (await client.get("/admin/beta-invites", headers=h)).json()["invites"]}
    assert states == {made["id"]: "used up", personal["id"]: "revoked"}


async def test_expired_codes_and_the_allowlist(client, auth, invite_only, monkeypatch):
    from datetime import timedelta

    from app.core.config import settings
    from app.db.base import utcnow
    from app.db.session import session_scope
    from app.models import BetaInvite
    h, _ = auth
    made = (await client.post("/admin/beta-invites", headers=h, json={"days": 1})).json()
    async with session_scope() as s:
        (await s.get(BetaInvite, made["id"])).expires_at = utcnow() - timedelta(minutes=1)
    assert (await _signup(client, "late@example.com", made["code"])).json()["error"]["code"] == "invite_invalid"

    monkeypatch.setattr(settings, "signup_allowlist", ["@partner.example", "ceo@agency.example"])
    assert (await _signup(client, "anyone@partner.example")).status_code == 200
    assert (await _signup(client, "ceo@agency.example")).status_code == 200
    assert (await _signup(client, "intern@agency.example")).status_code == 403


async def test_admin_views_are_for_platform_admins_only(client, auth):
    h, _ = auth
    other = (await _signup(client, "member@example.com")).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    for path in ("/admin/beta-invites", "/admin/users", "/admin/usage", "/admin/failed-jobs", "/admin/data", "/admin/errors"):
        assert (await client.get(path, headers=oh)).status_code == 403, path
        assert (await client.get(path, headers=h)).status_code == 200, path
    users = (await client.get("/admin/users?q=member", headers=h)).json()
    assert [u["email"] for u in users] == ["member@example.com"] and users[0]["workspaces"]


async def test_disabling_a_user_ends_their_sessions(client, auth):
    h, _ = auth
    victim = (await _signup(client, "abuser@example.com")).json()
    r = await client.patch(f"/admin/users/{victim['user']['id']}", headers=h, json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert (await client.post("/auth/login", json={"email": "abuser@example.com", "password": PASSWORD})).status_code == 401
    assert (await client.post("/auth/refresh", json={"refresh_token": victim["refresh_token"]})).status_code == 401
    me = (await client.get("/admin/users?q=owner", headers=h)).json()[0]
    assert (await client.patch(f"/admin/users/{me['id']}", headers=h, json={"is_active": False})).status_code == 409


async def test_errors_are_recorded_scrubbed_and_listed(client, auth):
    from app.db.session import get_session
    from app.main import app
    h, _ = auth
    r = await client.post("/client-errors", json={"message": "TypeError: x is undefined", "path": "/simulations/abc",
                                                   "detail": "at render (Results.tsx:10) Bearer eyJhbGciOiJIUzI1NiJ9.secretpayload sk-abcdefghijklmnop"})
    assert r.status_code == 204

    async def broken():
        raise RuntimeError("boom with sk-live-secretsecret1234")
        yield  # pragma: no cover
    app.dependency_overrides[get_session] = broken
    try:
        await client.get("/auth/me", headers={"Authorization": "Bearer x"})
    finally:
        app.dependency_overrides.clear()

    events = (await client.get("/admin/errors", headers=h)).json()
    assert events["last_24h"] == {"client": 1, "server": 1}
    text = str(events["events"])
    assert "TypeError: x is undefined" in text and "boom with" in text
    assert "sk-abcdefghijklmnop" not in text and "sk-live-secretsecret1234" not in text and "secretpayload" not in text


async def test_failed_jobs_usage_and_data_views(client, auth):
    from app.db.session import session_scope
    from app.models import Simulation
    h, _ = auth
    pr = (await client.post("/projects", json={"name": "Ops"}, headers=h)).json()
    body = {"name": "Broken run", "requirement": "Anything?", "content": {"type": "text", "text": "Hello world, this is a test post."},
            "audience": {"regions": ["AE"]}}
    sid = (await client.post(f"/projects/{pr['id']}/simulations", json=body, headers=h)).json()["id"]
    async with session_scope() as s:
        sim = await s.get(Simulation, sid)
        sim.status, sim.error = "failed", "Provider unavailable"
    failed = (await client.get("/admin/failed-jobs", headers=h)).json()
    assert failed[0]["id"] == sid and failed[0]["error"] == "Provider unavailable" and failed[0]["workspace"]
    usage = (await client.get("/admin/usage", headers=h)).json()
    assert usage["orgs"] and "shared_key_today" in usage
    await client.post("/barometers", headers=h, data={"country": "AE", "publisher": "FCSC"},
                      files={"file": ("bad.pdf", b"%PDF-1.4 broken", "application/pdf")})
    data = (await client.get("/admin/data", headers=h)).json()
    assert data["barometers"]["quarantined"] == 1 and data["recent_quarantined"][0]["reason"]
