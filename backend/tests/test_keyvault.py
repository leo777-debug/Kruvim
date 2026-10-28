"""Model-provider key vault and workspace spending limits."""
from __future__ import annotations

import httpx
import pytest

KEY = "sk-live-abcdefghijklmnop1234"


# ---- validation calls -----------------------------------------------------------------------------------------------
@pytest.fixture
def provider_answers(monkeypatch):
    """Answer validation requests locally and record what was sent."""
    from app.services import keyvault
    sent, status = [], {"code": 200}

    def handler(request: httpx.Request):
        sent.append(request)
        if status["code"] == "down":
            raise httpx.ConnectError("unreachable")
        return httpx.Response(status["code"], json={"data": []})

    def client(**kw):
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kw)
    monkeypatch.setattr(keyvault, "public_client", client)
    monkeypatch.setattr(keyvault, "model_client", client)
    return sent, status


async def test_each_provider_is_checked_with_a_free_authenticated_read(provider_answers):
    from app.services import keyvault
    sent, _ = provider_answers
    for provider in ("openai", "anthropic", "openrouter", "gemini"):
        assert (await keyvault.validate(provider, KEY)).ok
    urls = [str(r.url) for r in sent]
    assert urls == ["https://api.openai.com/v1/models", "https://api.anthropic.com/v1/models", "https://openrouter.ai/api/v1/key",
                    "https://generativelanguage.googleapis.com/v1beta/openai/models"]
    assert sent[0].headers["authorization"] == f"Bearer {KEY}"
    assert sent[1].headers["x-api-key"] == KEY and sent[1].headers["anthropic-version"] and "authorization" not in sent[1].headers
    assert (await keyvault.validate("custom", KEY, "https://llm.example.com/v1")).ok
    assert str(sent[-1].url) == "https://llm.example.com/v1/models"


async def test_validation_outcomes(provider_answers):
    from app.services import keyvault
    _, status = provider_answers
    status["code"] = 401
    with pytest.raises(keyvault.KeyRejected, match="rejected"):
        await keyvault.validate("openai", KEY)
    status["code"] = 429
    assert (await keyvault.validate("openai", KEY)).ok
    status["code"] = 500
    assert not (await keyvault.validate("openai", KEY)).ok
    status["code"] = "down"
    check = await keyvault.validate("openai", KEY)
    assert not check.ok and KEY not in check.message
    with pytest.raises(keyvault.KeyRejected):
        await keyvault.validate("openai", "")
    with pytest.raises(keyvault.KeyRejected, match="base URL"):
        await keyvault.validate("custom", KEY)


# ---- the vault through the API ----------------------------------------------------------------------------------------
async def test_add_view_rotate_check_and_delete(client, auth, accept_keys):
    h, _ = auth
    catalog = (await client.get("/model-keys", headers=h)).json()
    assert {"openai", "anthropic", "openrouter", "gemini"} <= {p["id"] for p in catalog["providers"]}
    assert catalog["keys"] == []

    r = await client.put("/model-keys/gemini", headers=h, json={"api_key": "AIzaFirstKey0000000000"})
    assert r.status_code == 200 and r.json()["status"] == "valid" and r.json()["hint"] == "AIz…0000"
    r = await client.put("/model-keys/gemini", headers=h, json={"api_key": "AIzaSecondKey111111111"})
    assert r.json()["rotated_at"] and r.json()["hint"].endswith("1111")
    listed = await client.get("/model-keys", headers=h)
    assert "AIzaSecondKey111111111" not in listed.text and "AIzaFirstKey" not in listed.text

    r = await client.post("/model-keys/gemini/check", headers=h)
    assert r.json()["status"] == "valid" and accept_keys[-1] == ("gemini", "AIzaSecondKey111111111", "")
    assert (await client.delete("/model-keys/gemini", headers=h)).status_code == 200
    assert (await client.get("/model-keys", headers=h)).json()["keys"] == []
    assert (await client.post("/model-keys/gemini/check", headers=h)).status_code == 404
    assert (await client.put("/model-keys/not-a-provider", headers=h, json={"api_key": "x"})).status_code == 422


async def test_refused_or_unverified_keys_are_never_stored(client, auth, accept_keys, monkeypatch):
    from app.services import keyvault
    h, _ = auth
    r = await client.put("/model-keys/openai", headers=h, json={"api_key": "bad-key-123456789"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "key_rejected"

    async def unreachable(*a, **kw):
        return keyvault.Check(False, "Could not reach OpenAI (ConnectError).")
    monkeypatch.setattr(keyvault, "validate", unreachable)
    r = await client.put("/model-keys/openai", headers=h, json={"api_key": KEY})
    assert r.status_code == 400 and r.json()["error"]["code"] == "key_unverified"
    assert (await client.get("/model-keys", headers=h)).json()["keys"] == []


async def test_runs_use_the_vault_key_for_the_chosen_provider(client, auth, accept_keys):
    from app.db.session import session_scope
    from app.services.providers import resolve
    h, session = auth
    org_id = session["orgs"][0]["id"]
    await client.put("/model-keys/openrouter", headers=h, json={"api_key": "sk-or-vaultkey-9999"})
    r = await client.put("/providers", headers=h, json={"preset": "openrouter", "voice_model": "m", "report_model": "m"})
    assert r.json()["api_key_set"] and r.json()["key_status"] == "valid" and r.json()["key_provider"] == "openrouter"
    async with session_scope() as s:
        res = await resolve(s, org_id)
    assert res.source == "org" and res.settings.api_key == "sk-or-vaultkey-9999" and not res.metered
    # Removing the key leaves the provider choice but no key: runs fail clearly instead of using someone else's.
    await client.delete("/model-keys/openrouter", headers=h)
    async with session_scope() as s:
        assert (await resolve(s, org_id)).settings.api_key == ""


async def test_only_admins_manage_keys_and_workspaces_are_isolated(client, auth, accept_keys):
    h, _ = auth
    await client.put("/model-keys/openai", headers=h, json={"api_key": KEY})
    inv = (await client.post("/members/invites", headers=h, json={"email": "m@example.com", "role": "member"})).json()
    m = (await client.post("/auth/invites/accept", json={"token": inv["accept_url"].rsplit("/", 1)[-1], "password": "member-pass-123"})).json()
    mh = {"Authorization": f"Bearer {m['access_token']}"}
    assert (await client.put("/model-keys/openai", headers=mh, json={"api_key": KEY})).status_code == 403
    assert (await client.delete("/model-keys/openai", headers=mh)).status_code == 403
    assert (await client.put("/limits", headers=mh, json={"monthly_calls": 5})).status_code == 403
    assert len((await client.get("/model-keys", headers=mh)).json()["keys"]) == 1      # members see that a key exists, masked

    other = (await client.post("/auth/register", json={"email": "o@example.com", "password": "other-password-1"})).json()
    oh = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get("/model-keys", headers=oh)).json()["keys"] == []
    assert (await client.post("/model-keys/openai/check", headers=oh)).status_code == 404


# ---- spending limits ----------------------------------------------------------------------------------------------
def _own_key(prices=False):
    from app.services.llm import ProviderSettings
    from app.services.providers import Resolved
    return Resolved(ProviderSettings(provider="openai", preset="openai", api_key="k", voice_model="m",
                                     price_in=1.0 if prices else None, price_out=2.0 if prices else None), "org", None)


async def test_workspace_limits_stop_calls_on_any_key():
    from app.services import spend
    from app.services.llm import BudgetExceeded, Usage
    u = spend.guard(Usage(), "org-l1", _own_key(), limits={"monthly_calls": 2})
    await u.before_call()
    await u.before_call()
    with pytest.raises(BudgetExceeded, match="monthly limit of 2"):
        await u.before_call()

    u = spend.guard(Usage(), "org-l2", _own_key(), limits={"member_daily_calls": 1}, user_id="user-1")
    await u.before_call()
    with pytest.raises(BudgetExceeded, match="per member"):
        await u.before_call()
    # Another member of the same workspace still has their own allowance.
    await spend.guard(Usage(), "org-l2", _own_key(), limits={"member_daily_calls": 1}, user_id="user-2").before_call()


async def test_dollar_limit_counts_actual_token_cost():
    from app.services import spend
    from app.services.llm import BudgetExceeded, Usage
    res = _own_key(prices=True)                       # $1 per 1M input tokens, $2 per 1M output tokens
    u = spend.guard(Usage(), "org-usd", res, limits={"monthly_usd": 1.0})
    await u.before_call()
    u.add("openai", "m", "voice", inp=400_000, cached=0, out=300_000, secs=1)    # $0.40 + $0.60 = $1.00
    with pytest.raises(BudgetExceeded, match=r"\$1.00"):
        await u.before_call()
    assert (await spend.usage_now("org-usd"))["month_usd"] == 1.0


async def test_limits_api_and_refusing_runs_that_cannot_fit(client, auth):
    from app.core.errors import QuotaExceeded
    from app.services import spend
    h, session = auth
    r = await client.put("/limits", headers=h, json={"monthly_calls": 100, "monthly_usd": 25, "member_daily_calls": 40})
    assert r.status_code == 200 and r.json()["limits"] == {"monthly_calls": 100, "monthly_usd": 25.0, "member_daily_calls": 40}
    assert (await client.put("/limits", headers=h, json={"monthly_calls": 0})).status_code == 422
    got = (await client.get("/limits", headers=h)).json()
    assert got["used"]["month_calls"] == 0 and got["used"]["member_today_calls"] == 0

    class Org:
        id = session["orgs"][0]["id"]
        settings = {"limits": {"monthly_calls": 100, "member_daily_calls": 40}}
    await spend.check_room(Org, session["user"]["id"], 30)
    with pytest.raises(QuotaExceeded, match="40 left today"):
        await spend.check_room(Org, session["user"]["id"], 41)
    with pytest.raises(QuotaExceeded, match="100 left this month"):
        await spend.check_room(Org, None, 101)
