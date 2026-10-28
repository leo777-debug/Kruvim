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


# ---- H1/M6: server-side requests to user-supplied addresses ---------------------------------------------------------
async def test_provider_addresses_cannot_reach_internal_network(client, auth, monkeypatch):
    from app.core.config import settings
    monkeypatch.setattr(settings, "allow_private_model_urls", False)
    headers, _ = auth

    r = await client.put("/providers", headers=headers, json={"preset": "ollama", "base_url": "http://localhost:11434/v1"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "local_models_disabled"
    r = await client.put("/providers", headers=headers, json={"preset": "custom", "base_url": "http://169.254.169.254/latest"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "bad_base_url"

    # Resolves to a private address at connect time: refused, and the key never appears in the message.
    r = await client.post("/providers/test", headers=headers, json={"preset": "custom", "base_url": "https://127.0.0.1:9/v1",
                                                                     "api_key": "sk-secret-value-123456", "voice_model": "m"})
    body = r.json()
    assert body["ok"] is False and "sk-secret-value-123456" not in body["message"]
    r = await client.post("/providers/models", headers=headers, json={"preset": "custom", "base_url": "https://localhost/v1"})
    assert r.json()["models"] == []

    # Hosted presets always talk to their official address.
    r = await client.put("/providers", headers=headers, json={"preset": "openai", "base_url": "https://evil.example/v1", "api_key": "sk-x"})
    assert r.status_code == 200 and r.json()["base_url"] == "https://api.openai.com/v1"


async def test_public_client_blocks_private_and_mapped_addresses():
    import pytest

    from app.core.netguard import BlockedAddress, is_public, public_client
    assert not is_public("10.0.0.1") and not is_public("::ffff:127.0.0.1") and not is_public("169.254.169.254")
    assert is_public("8.8.8.8")
    async with public_client(timeout=3) as c:
        for url in ("http://127.0.0.1:9/", "http://localhost:9/", "http://[::1]:9/"):
            with pytest.raises(BlockedAddress):
                await c.get(url)
