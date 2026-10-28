"""Regression tests for the Phase 2 security audit findings."""
from __future__ import annotations

VICTIM = {"email": "owner@example.com", "password": "correct-horse-battery"}


async def _register(client, email, password="attacker-password-1", org="Attacker Org"):
    r = await client.post("/auth/register", json={"email": email, "password": password, "name": email.split("@")[0], "org_name": org})
    assert r.status_code == 200, r.text
    data = r.json()
    return {"Authorization": f"Bearer {data['access_token']}"}, data


async def _invite(client, headers, email):
    r = await client.post("/members/invites", headers=headers, json={"email": email, "role": "member"})
    assert r.status_code == 200, r.text
    return r.json()["accept_url"].rsplit("/", 1)[-1]


# ---- C1: invites never sign in to an existing account without proof of ownership ------------------------------------
async def test_invite_cannot_take_over_existing_account(client, auth):
    attacker, _ = await _register(client, "attacker@example.com")
    token = await _invite(client, attacker, VICTIM["email"])

    r = await client.post("/auth/invites/accept", json={"token": token})
    assert r.status_code == 401 and r.json()["error"]["code"] == "password_required"
    r = await client.post("/auth/invites/accept", json={"token": token, "password": "wrong-password-123"})
    assert r.status_code == 401
    # A different signed-in user is not the invited account either.
    r = await client.post("/auth/invites/accept", headers=attacker, json={"token": token})
    assert r.status_code == 401


async def test_invite_accepted_by_owner_with_password_or_session(client, auth):
    victim_headers, _ = auth
    attacker, _ = await _register(client, "admin2@example.com", org="Second Org")
    token = await _invite(client, attacker, VICTIM["email"])
    r = await client.post("/auth/invites/accept", json={"token": token, "password": VICTIM["password"]})
    assert r.status_code == 200 and r.json()["user"]["email"] == VICTIM["email"]

    other, _ = await _register(client, "third@example.com", org="Third Org")
    token = await _invite(client, other, VICTIM["email"])
    r = await client.post("/auth/invites/accept", headers=victim_headers, json={"token": token})
    assert r.status_code == 200 and len(r.json()["orgs"]) == 3
