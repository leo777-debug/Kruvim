"""Invitation links grant workspace membership, never proof of an existing identity."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.ratelimit import _local
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import AuditLog, Invite, Membership, RefreshToken, User

PASSWORD = "recipient-secret-password"
ATTACKER_PASSWORD = "inviter-secret-password"


@pytest.fixture
async def invitation(client, auth):
    # The bootstrap account is the platform admin. Neither participant is one.
    accounts = []
    for email, password in (("victim@example.com", PASSWORD), ("inviter@example.com", ATTACKER_PASSWORD)):
        response = await client.post("/auth/register", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        account = response.json()
        assert account["user"]["is_superuser"] is False
        accounts.append(account)
    victim, inviter = accounts
    headers = {"Authorization": f"Bearer {inviter['access_token']}"}
    response = await client.post("/members/invites", headers=headers,
                                 json={"email": victim["user"]["email"], "role": "member"})
    assert response.status_code == 200, response.text
    invite = response.json()
    return victim, inviter, headers, invite, invite["accept_url"].rsplit("/", 1)[1]


async def state():
    """A rejected acceptance must not persist any identity, membership or session writes."""
    async with session_scope() as s:
        return {
            "users": [(u.id, u.name, u.password_hash, u.last_login_at) for u in
                      (await s.execute(select(User).order_by(User.id))).scalars()],
            "memberships": [(m.id, m.org_id, m.user_id, m.role) for m in
                            (await s.execute(select(Membership).order_by(Membership.id))).scalars()],
            "sessions": [(t.id, t.token_hash, t.revoked_at) for t in
                         (await s.execute(select(RefreshToken).order_by(RefreshToken.id))).scalars()],
            "invites": [(i.id, i.accepted_at) for i in
                        (await s.execute(select(Invite).order_by(Invite.id))).scalars()],
            "audit": [a.id for a in (await s.execute(select(AuditLog).order_by(AuditLog.id))).scalars()],
        }


@pytest.mark.parametrize("credentials,status", [
    ({}, 422), ({"password": None}, 422), ({"password": ""}, 422),
    ({"password": "wrong-recipient-password"}, 401),
    ({"password": ATTACKER_PASSWORD}, 401),
])
@pytest.mark.parametrize("authenticated_inviter", [False, True])
async def test_existing_user_requires_their_own_password(client, invitation, credentials, status, authenticated_inviter):
    victim, _, headers, _, token = invitation
    before = await state()
    response = await client.post("/auth/invites/accept", json={"token": token, **credentials},
                                 headers=headers if authenticated_inviter else {})
    assert response.status_code == status, response.text
    assert "access_token" not in response.json() and "refresh_token" not in response.json()
    assert await state() == before
    # The ordinary inviter still cannot enter the victim's original workspace.
    response = await client.get("/orgs/current", headers={**headers, "X-Org-Id": victim["orgs"][0]["id"]})
    assert response.status_code == 403


async def test_existing_user_password_allows_acceptance_and_refresh_but_not_replay(client, invitation):
    victim, inviter, _, invite, token = invitation
    response = await client.post("/auth/invites/accept", json={"token": token, "password": PASSWORD, "name": "Do not overwrite"})
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["user"] == victim["user"]
    orgs = {o["id"]: o["role"] for o in accepted["orgs"]}
    assert orgs[victim["orgs"][0]["id"]] == "owner"
    assert orgs[inviter["orgs"][0]["id"]] == "member"
    assert (await client.get("/orgs/current", headers={"Authorization": f"Bearer {accepted['access_token']}"})).json()["id"] == inviter["orgs"][0]["id"]
    refreshed = await client.post("/auth/refresh", json={"refresh_token": accepted["refresh_token"]})
    assert refreshed.status_code == 200 and refreshed.json()["user"]["id"] == victim["user"]["id"]
    async with session_scope() as s:
        assert (await s.get(Invite, invite["id"])).accepted_at is not None
    before = await state()
    replay = await client.post("/auth/invites/accept", json={"token": token, "password": PASSWORD})
    assert replay.status_code == 404
    assert await state() == before


async def test_disabled_user_cannot_accept_even_with_correct_password(client, invitation):
    victim, _, _, _, token = invitation
    async with session_scope() as s:
        (await s.get(User, victim["user"]["id"])).is_active = False
    before = await state()
    response = await client.post("/auth/invites/accept", json={"token": token, "password": PASSWORD})
    assert response.status_code == 401
    assert await state() == before


@pytest.mark.parametrize("kind", ["expired", "revoked", "invalid"])
async def test_unusable_invite_cannot_issue_session(client, invitation, kind):
    _, _, _, invite, token = invitation
    async with session_scope() as s:
        row = await s.get(Invite, invite["id"])
        if kind == "expired":
            row.expires_at = utcnow() - timedelta(seconds=1)
        elif kind == "revoked":
            await s.delete(row)
        else:
            token = "invalid-invitation-token"
    before = await state()
    response = await client.post("/auth/invites/accept", json={"token": token, "password": PASSWORD})
    assert response.status_code == 404
    assert await state() == before


async def test_new_recipient_can_create_account(client, invitation):
    _, inviter, headers, _, _ = invitation
    response = await client.post("/members/invites", headers=headers,
                                 json={"email": "NEW@example.com", "role": "viewer"})
    assert response.status_code == 200, response.text
    token = response.json()["accept_url"].rsplit("/", 1)[1]
    before = await state()
    for credentials in ({}, {"password": None}, {"password": ""}, {"password": "short"}):
        response = await client.post("/auth/invites/accept", json={"token": token, **credentials})
        assert response.status_code == 422
        assert await state() == before
    response = await client.post("/auth/invites/accept", json={"token": token, "password": PASSWORD, "name": "New recipient"})
    assert response.status_code == 200, response.text
    accepted = response.json()
    assert accepted["user"]["email"] == "new@example.com"
    assert accepted["user"]["name"] == "New recipient"
    assert accepted["user"]["is_superuser"] is False
    assert [(o["id"], o["role"]) for o in accepted["orgs"]] == [(inviter["orgs"][0]["id"], "viewer")]
    assert (await client.post("/auth/login", json={"email": "new@example.com", "password": PASSWORD})).status_code == 200


@pytest.mark.parametrize("scope", ["ip", "account"])
async def test_invite_password_attempts_share_login_limits(client, invitation, monkeypatch, scope):
    victim, _, _, _, token = invitation
    _local.clear()
    monkeypatch.setattr(settings, "rate_limit_auth_per_minute", 1)
    wrong = {"token": token, "password": "wrong-recipient-password"}
    assert (await client.post("/auth/invites/accept", json=wrong,
                              headers={"X-Forwarded-For": "192.0.2.1"})).status_code == 401
    before = await state()
    headers = {"X-Forwarded-For": "192.0.2.1" if scope == "ip" else "192.0.2.2"}
    response = await client.post("/auth/invites/accept", json={"token": token, "password": PASSWORD}, headers=headers)
    assert response.status_code == 429
    response = await client.post("/auth/login", json={"email": victim["user"]["email"], "password": PASSWORD}, headers=headers)
    assert response.status_code == 429
    assert await state() == before
