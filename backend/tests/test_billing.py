"""Payment trust boundaries and spending limits; no live payment/model requests."""
import asyncio
import base64
import hashlib
import hmac
import json
import time
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import BillingAccount, BillingGrant, BillingOrder, BillingSeat, Membership, SpendReservation
from app.services import billing, spend_budget
from app.services.llm import ProviderSettings, Usage, make_llm
from app.services.llm.errors import BudgetPause, ProviderFailure


@pytest.fixture
def payments(monkeypatch):
    monkeypatch.setattr(settings, "billing_enabled", True)
    monkeypatch.setattr(settings, "dodo_api_key", "test-only-key")
    monkeypatch.setattr(settings, "dodo_business_id", "bus_test")
    monkeypatch.setattr(settings, "dodo_webhook_key", "whsec_" + base64.b64encode(b"test-webhook-secret").decode())
    monkeypatch.setattr(settings, "dodo_subscription_product_id", "p_subscription")
    monkeypatch.setattr(settings, "dodo_topup_product_id", "p_topup")
    spend_budget.locks.clear()


def signed(event, *, event_id="evt_1", stamp=None):
    raw = json.dumps({"business_id": "bus_test", **event}).encode()
    stamp = str(stamp or int(time.time()))
    signature = base64.b64encode(hmac.new(b"test-webhook-secret", event_id.encode() + b"." + stamp.encode()
        + b"." + raw, hashlib.sha256).digest()).decode()
    return raw, {"webhook-id": event_id, "webhook-timestamp": stamp, "webhook-signature": "v1," + signature}


async def seed_subscription(org_id, *, remaining=10_000_000, suffix="test"):
    now = utcnow()
    async with session_scope() as s:
        a = await billing.account(s, org_id)
        a.customer_id, a.subscription_id, a.status = f"cus_{suffix}", f"sub_{suffix}", "active"
        a.period_start, a.period_end = now, now + timedelta(days=30)
        a.monthly_remaining = remaining
    return now


async def test_unpaid_simulations_blocked_but_billing_and_history_readable(client, auth, payments):
    h, data = auth
    project = (await client.post("/projects", headers=h, json={"name": "Paywall"})).json()
    r = await client.post(f"/projects/{project['id']}/simulations", headers=h, json={})
    assert r.status_code == 402 and r.json()["error"]["code"] == "subscription_required"
    assert (await client.get("/simulations", headers=h)).status_code == 200
    state = (await client.get("/billing", headers=h)).json()
    assert state["active"] is False and state["available"] == 0
    assert (await client.get("/usage", headers=h)).status_code == 200
    # A browser success URL does not create an entitlement.
    assert (await client.get("/billing?checkout=returned", headers=h)).json()["active"] is False


async def test_webhook_rejects_invalid_signature_old_timestamp_and_wrong_business(client, payments):
    event = {"type": "payment.succeeded", "data": {"payment_id": "pay_test"}}
    raw, headers = signed(event)
    headers["webhook-signature"] = "v1,forged"
    assert (await client.post("/billing/webhook", content=raw, headers=headers)).status_code == 401
    raw, headers = signed(event, stamp=int(time.time()) - 3600)
    assert (await client.post("/billing/webhook", content=raw, headers=headers)).status_code == 401
    raw, headers = signed({**event, "business_id": "other"})
    assert (await client.post("/billing/webhook", content=raw, headers=headers)).status_code == 401


async def test_paid_cycle_idempotency_topups_renewal_and_refund(client, auth, payments, monkeypatch):
    h, data = auth
    org_id = data["orgs"][0]["id"]
    now = utcnow()
    async with session_scope() as s:
        order = BillingOrder(org_id=org_id, kind="subscription", product_id="p_subscription", quantity=1,
                             budget_micros=10_000_000)
        s.add(order)
        await s.flush()
        order_id = order.id
    sub = {"subscription_id": "sub_test", "product_id": "p_subscription", "quantity": 1, "status": "active",
           "customer": {"customer_id": "cus_test"}, "metadata": {"kruvim_order_id": order_id}}
    payment = {"payment_id": "pay_first", "business_id": "bus_test", "status": "succeeded", "currency": "AED",
        "total_amount": 5000, "subscription_id": "sub_test", "charge_type": "new",
        "metadata": {"kruvim_order_id": order_id}, "service_periods": [{"subscription_id": "sub_test",
            "starts_at": now.isoformat(), "ends_at": (now + timedelta(days=30)).isoformat()}]}
    async def fake_dodo(method, path, **kwargs):
        return sub if path.startswith("/subscriptions/") else payment
    monkeypatch.setattr(billing, "dodo", fake_dodo)

    async def deliver(kind, identity, event_id):
        raw, headers = signed({"type": kind, "data": identity}, event_id=event_id)
        r = await client.post("/billing/webhook", content=raw, headers=headers)
        assert r.status_code == 200, r.text

    # Card authorisation alone must not grant credits; the payment must succeed.
    await deliver("subscription.active", {"subscription_id": "sub_test"}, "evt_active")
    assert not (await client.get("/billing", headers=h)).json()["active"]
    await deliver("payment.succeeded", {"payment_id": "pay_first"}, "evt_first")
    await deliver("payment.succeeded", {"payment_id": "pay_first"}, "evt_first")
    await deliver("payment.succeeded", {"payment_id": "pay_first"}, "evt_duplicate_payment")
    state = (await client.get("/billing", headers=h)).json()
    assert state["active"] and state["available"] == 10000
    r = await spend_budget.reserve(org_id, 9_000_000)
    await spend_budget.settle(r, 8_000_000)
    # A different successful event for the same cycle cannot reset consumed credits.
    payment["payment_id"] = "pay_same_period"
    await deliver("payment.succeeded", {"payment_id": "pay_same_period"}, "evt_same_period")
    assert (await client.get("/billing", headers=h)).json()["available_aed"] == 2
    async with session_scope() as s:
        topup = BillingOrder(org_id=org_id, kind="topup", product_id="p_topup", quantity=1,
                             seat_user_id=data["user"]["id"], price_minor=2000, budget_micros=10_000_000)
        s.add(topup)
        await s.flush()
        topup_id = topup.id
    payment = {"payment_id": "pay_topup", "business_id": "bus_test", "status": "succeeded", "currency": "AED",
        "total_amount": 2000, "customer": {"customer_id": "cus_test"},
        "metadata": {"kruvim_order_id": topup_id}, "product_cart": [{"product_id": "p_topup", "quantity": 1}]}
    await deliver("payment.succeeded", {"payment_id": "pay_topup"}, "evt_topup")
    await deliver("payment.succeeded", {"payment_id": "pay_topup"}, "evt_topup")
    await deliver("payment.succeeded", {"payment_id": "pay_topup"}, "evt_topup_duplicate_payment")
    payment["payment_id"] = "pay_second_for_same_order"
    await deliver("payment.succeeded", {"payment_id": payment["payment_id"]}, "evt_topup_other")
    assert (await client.get("/billing", headers=h)).json()["available_aed"] == 12
    payment = {"payment_id": "pay_renewal", "business_id": "bus_test", "status": "succeeded", "currency": "AED",
        "total_amount": 5000, "subscription_id": "sub_test", "charge_type": "renewal",
        "service_periods": [{"subscription_id": "sub_test", "starts_at": (now + timedelta(seconds=1)).isoformat(),
                            "ends_at": (now + timedelta(days=60)).isoformat()}]}
    await deliver("subscription.renewed", {"subscription_id": "sub_test", "payment_id": "pay_renewal"}, "evt_renew")
    await deliver("payment.succeeded", {"payment_id": "pay_renewal"}, "evt_renew_payment")
    state = (await client.get("/billing", headers=h)).json()
    assert state["available_aed"] == 20 and state["purchased_remaining_aed"] == 10
    await deliver("refund.succeeded", {"payment_id": "pay_topup"}, "evt_refund")
    assert not (await client.get("/billing", headers=h)).json()["active"]
    async with session_scope() as s:
        assert (await s.execute(select(func.count()).select_from(BillingGrant))).scalar() == 4


async def test_concurrent_requests_cannot_exceed_cap_and_settlement_preserves_new_cycle(auth, payments):
    _, data = auth
    org_id = data["orgs"][0]["id"]
    user_id = data["user"]["id"]
    await seed_subscription(org_id)
    results = await asyncio.gather(spend_budget.reserve(org_id, 7_000_000), spend_budget.reserve(org_id, 7_000_000),
                                   return_exceptions=True)
    assert sum(isinstance(r, BudgetPause) for r in results) == 1
    reservation = next(r for r in results if isinstance(r, str))
    await spend_budget.settle(reservation, 2_000_000)
    await spend_budget.settle(reservation, 2_000_000)
    async with session_scope() as s:
        assert (await s.get(BillingSeat, (org_id, user_id))).monthly_remaining == 8_000_000
    r = await spend_budget.reserve(org_id, 1_000_000)
    async with session_scope() as s:
        a = await s.get(BillingAccount, org_id)
        a.period_start = utcnow() + timedelta(days=30)
        seat = await s.get(BillingSeat, (org_id, user_id))
        seat.period_start, seat.monthly_remaining = a.period_start, 10_000_000
    await spend_budget.settle(r, 100_000)
    async with session_scope() as s:
        assert (await s.get(BillingSeat, (org_id, user_id))).monthly_remaining == 10_000_000


async def test_model_requests_settle_actual_usage_and_timeout_does_not_retry(auth, payments, monkeypatch):
    _, data = auth
    org_id = data["orgs"][0]["id"]
    await seed_subscription(org_id)
    monkeypatch.setattr(settings, "billing_model_prices", {"test-model": {"input": .1, "output": .4}})
    llm = make_llm(ProviderSettings(provider="openai", base_url="https://model.invalid/v1", voice_model="test-model",
                                  billing_org_id=org_id, billing_metered=True))
    await llm.client.aclose()
    requests = []
    async def success(request):
        requests.append(request)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 600, "completion_tokens": 80},
            "choices": [{"message": {"content": '{"ok":true}'}}]})
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(success))
    usage = Usage()
    assert await llm.complete_json(system="test", user="hello", role="voice", max_tokens=100, usage=usage) == {"ok": True}
    assert usage.calls == 1 and usage.input_tokens == 600
    async with session_scope() as s:
        seat = await s.get(BillingSeat, (org_id, data["user"]["id"]))
        assert seat.monthly_remaining == 10_000_000 - 338
    await llm.client.aclose()
    async def timeout(request):
        requests.append(request)
        raise httpx.ReadTimeout("uncertain provider response", request=request)
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(timeout))
    with pytest.raises(ProviderFailure):
        await llm.complete(system="test", user="hello", role="voice", max_tokens=100, usage=Usage())
    assert len(requests) == 2
    async with session_scope() as s:
        reservations = (await s.execute(select(SpendReservation).order_by(SpendReservation.created_at))).scalars().all()
        assert [r.status for r in reservations] == ["settled", "reserved"]
    monkeypatch.setattr(settings, "billing_model_prices", {})
    with pytest.raises(BudgetPause):
        await llm.complete(system="test", user="hello", role="voice", max_tokens=100, usage=Usage())
    assert len(requests) == 2
    await llm.aclose()


async def test_workspace_ai_rate_limit_blocks_provider_calls_until_next_minute(auth, payments, monkeypatch):
    _, data = auth
    org_id = data["orgs"][0]["id"]
    await seed_subscription(org_id)
    now = utcnow().replace(second=0, microsecond=0)
    monkeypatch.setattr(spend_budget, "utcnow", lambda: now)
    monkeypatch.setattr(settings, "billing_ai_calls_per_minute", 1)
    monkeypatch.setattr(settings, "billing_model_prices", {"test-model": {"input": .1, "output": .4}})
    llm = make_llm(ProviderSettings(provider="openai", base_url="https://model.invalid/v1", voice_model="test-model",
                                    billing_org_id=org_id, billing_metered=True))
    await llm.client.aclose()
    calls = []

    async def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as llm.client:
        async def complete():
            return await llm.complete(system="test", user="hello", role="voice", max_tokens=100, usage=Usage())

        assert await complete() == "ok"
        with pytest.raises(BudgetPause) as blocked:
            await complete()
        assert blocked.value.state["code"] == "ai_rate_limited"
        assert len(calls) == 1
        now += timedelta(minutes=1)
        assert await complete() == "ok"
        assert len(calls) == 2


async def test_platform_spend_cap_is_shared_and_releases_only_unused_reservations(client, auth, payments, monkeypatch):
    _, data = auth
    first = data["orgs"][0]["id"]
    signup = await client.post("/auth/register", json={"email": "second@example.com",
        "password": "correct-horse-battery", "name": "Second", "org_name": "Second"})
    assert signup.status_code == 200, signup.text
    second = signup.json()["orgs"][0]["id"]
    await seed_subscription(first)
    await seed_subscription(second, suffix="second")
    monkeypatch.setattr(settings, "billing_platform_monthly_budget_aed", 10)
    now = utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(spend_budget, "utcnow", lambda: now)

    results = await asyncio.gather(spend_budget.reserve(first, 7_000_000), spend_budget.reserve(second, 7_000_000),
                                   return_exceptions=True)
    winner = next(i for i, result in enumerate(results) if isinstance(result, str))
    loser = 1 - winner
    assert isinstance(results[loser], BudgetPause)
    assert results[loser].state["code"] == "platform_budget_exhausted"
    blocked_org = (first, second)[loser]
    async with session_scope() as s:
        assert (await s.get(BillingAccount, blocked_org)).monthly_remaining == 10_000_000
    await asyncio.gather(*(spend_budget.settle(results[winner], 4_000_000) for _ in range(2)))
    outstanding = await spend_budget.reserve(blocked_org, 6_000_000)
    with pytest.raises(BudgetPause) as blocked:
        await spend_budget.reserve(blocked_org, 1)
    assert blocked.value.state["code"] == "platform_budget_exhausted"

    now = (now + timedelta(days=32)).replace(day=1)
    await spend_budget.reserve(blocked_org, 4_000_000)
    await spend_budget.settle(outstanding, 1_000_000)
    await spend_budget.reserve(blocked_org, 1_000_000)
    with pytest.raises(BudgetPause) as blocked:
        await spend_budget.reserve((first, second)[winner], 6_000_000)
    assert blocked.value.state["code"] == "platform_budget_exhausted"


async def test_checkout_uses_server_catalog_and_cannot_grant_access(client, auth, payments, monkeypatch):
    h, _ = auth
    seen = []
    async def fake_dodo(method, path, **kw):
        seen.append((method, path, kw))
        if method == "GET":
            return {"price": {"type": "recurring_price", "price": 5000, "currency": "AED", "tax_inclusive": True,
                              "payment_frequency_count": 1, "payment_frequency_interval": "Month"}}
        return {"session_id": "cks_test", "checkout_url": "https://test.checkout.dodopayments.com/session/cks_test"}
    monkeypatch.setattr(billing, "dodo", fake_dodo)
    r = await client.post("/billing/checkout", headers=h, json={"kind": "subscription", "seats": 1, "price": 1})
    assert r.status_code == 200, r.text
    body = seen[-1][2]["body"]
    assert body["product_cart"] == [{"product_id": "p_subscription", "quantity": 1}]
    assert body["subscription_data"]["trial_period_days"] == 0
    assert (await client.get("/billing", headers=h)).json()["active"] is False
    again = await client.post("/billing/checkout", headers=h, json={"kind": "subscription", "seats": 1})
    assert again.status_code == 200 and again.json() == r.json()
    assert sum(method == "POST" for method, _, _ in seen) == 1
    assert (await client.post("/billing/checkout", headers=h, json={"kind": "topup"})).status_code == 402


async def test_member_cannot_subscribe_or_manage_billing_and_other_workspace_is_private(client, auth, payments):
    h, data = auth
    org_id = data["orgs"][0]["id"]
    async with session_scope() as s:
        member = (await s.execute(select(Membership).where(Membership.org_id == org_id))).scalar_one()
        member.role = "member"
    assert (await client.post("/billing/checkout", headers=h, json={"kind": "subscription"})).status_code == 403
    assert (await client.post("/billing/portal", headers=h, json={})).status_code == 403
    second = (await client.post("/auth/register", json={"email": "other@example.com", "password": "correct-horse-battery",
        "name": "Other", "org_name": "Other"})).json()
    other = {"Authorization": "Bearer " + second["access_token"], "X-Org-Id": org_id}
    assert (await client.get("/billing", headers=other)).status_code == 403


async def test_receipt_replay_is_free_and_expired_membership_cannot_spend(auth, payments, monkeypatch):
    from app.services.providers import Resolved
    from app.services.token_budget import Work, scope
    _, data = auth
    org_id = data["orgs"][0]["id"]
    await seed_subscription(org_id)
    monkeypatch.setattr(settings, "billing_model_prices", {"test-model": {"input": .1, "output": .4}})
    provider = ProviderSettings(provider="openai", base_url="https://model.invalid/v1", voice_model="test-model",
                                billing_org_id=org_id, billing_metered=True)
    llm = make_llm(provider)
    await llm.client.aclose()
    calls = []
    async def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 100, "completion_tokens": 50},
            "choices": [{"message": {"content": '{"ok":true}'}}]})
    llm.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    work = Work(org_id, None, "billing-replay", Resolved(provider, "env", None))
    async with scope(work):
        for _ in range(2):
            assert await llm.complete_json(system="test", user="same", role="voice", max_tokens=100,
                usage=Usage(), operation_key="same") == {"ok": True}
    assert len(calls) == 1
    async with session_scope() as s:
        assert (await s.execute(select(func.count()).select_from(SpendReservation))).scalar() == 1
        a = await s.get(BillingAccount, org_id)
        a.period_end = utcnow() - timedelta(seconds=1)
    with pytest.raises(BudgetPause):
        await llm.complete(system="test", user="new", role="voice", max_tokens=100, usage=Usage())
    assert len(calls) == 1
    await llm.aclose()


async def test_paid_openai_usage_blocks_only_the_spent_seat_and_member_can_top_up(client, auth, payments, monkeypatch):
    from app.services.providers import resolve

    owner_headers, owner = auth
    org_id = owner["orgs"][0]["id"]
    member = (await client.post("/auth/register", json={"email": "member@example.com", "name": "Member",
        "password": "correct-horse-battery", "org_name": "Member"})).json()
    user_id = member["user"]["id"]
    headers = {"Authorization": "Bearer " + member["access_token"], "X-Org-Id": org_id}
    await seed_subscription(org_id, remaining=20_000_000)
    monkeypatch.setattr(settings, "billing_openai_api_key", "test-private-openai-key")
    monkeypatch.setattr(settings, "billing_usd_to_aed", 1)
    monkeypatch.setattr(settings, "billing_model_prices", {settings.billing_openai_model:
        {"input": 10, "cached": 5, "output": 20}})
    async with session_scope() as s:
        a = await s.get(BillingAccount, org_id)
        a.seats = 2
        s.add(Membership(org_id=org_id, user_id=user_id, role="member"))
        res = await resolve(s, org_id, simulation=True, user_id=user_id)

    assert (await client.get("/billing", headers=headers)).json()["available_aed"] == 10
    llm = make_llm(res.settings)
    assert llm.client.headers["Authorization"] == "Bearer test-private-openai-key"
    await llm.aclose()
    calls = []

    async def respond(request):
        calls.append(request)
        assert request.url == "https://api.openai.com/v1/chat/completions"
        assert json.loads(request.content)["max_completion_tokens"] == 10_000
        return httpx.Response(200, json={"usage": {"prompt_tokens": 15_000, "completion_tokens": 10_000,
            "prompt_tokens_details": {"cached_tokens": 10_000}}, "choices": [{"message": {"content": "ok"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as llm.client:
        async def run_model():
            return await llm.complete(system="test", user="a" * 15_000, role="voice", max_tokens=10_000, usage=Usage())

        assert await run_model() == "ok"
        assert (await client.get("/billing", headers=headers)).json()["available_aed"] == 9.70
        reservation = await spend_budget.reserve(org_id, 9_700_000, user_id)
        await spend_budget.settle(reservation, 9_700_000)
        with pytest.raises(BudgetPause) as blocked:
            await run_model()
        assert blocked.value.state["available_aed"] == 0
    assert len(calls) == 1
    assert (await client.get("/billing", headers=owner_headers)).json()["available_aed"] == 10

    project = (await client.post("/projects", headers=headers, json={"name": "Paid seat"})).json()
    denied = await client.post(f"/projects/{project['id']}/simulations", headers=headers,
                               json={"content": {"type": "text", "text": "Test content"}})
    assert denied.status_code == 402, denied.text
    assert denied.json()["error"]["details"]["actions"][0]["url"] == "/usage"

    async def dodo_request(method, path, **kwargs):
        if path == "/products/p_topup":
            return {"price": {"type": "one_time_price", "price": 2000, "currency": "AED", "tax_inclusive": True}}
        if path == "/checkouts":
            assert kwargs["body"]["customer"]["email"] == "member@example.com"
            return {"session_id": "cks_member", "checkout_url": "https://test.checkout.dodopayments.com/session/cks_member"}
        return {"payment_id": "pay_member", "business_id": "bus_test", "status": "succeeded",
            "currency": "AED", "total_amount": 2000, "checkout_session_id": "cks_member",
            "metadata": {"kruvim_order_id": order_id}, "product_cart": [{"product_id": "p_topup", "quantity": 1}]}

    monkeypatch.setattr(billing, "dodo", dodo_request)
    checkout = await client.post("/billing/checkout", headers=headers, json={"kind": "topup", "seats": 2})
    assert checkout.status_code == 200, checkout.text
    async with session_scope() as s:
        order = await s.scalar(select(BillingOrder).where(BillingOrder.session_id == "cks_member"))
        assert (order.seat_user_id, order.price_minor, order.budget_micros) == (user_id, 2000, 10_000_000)
        order_id = order.id
    raw, signature = signed({"type": "payment.succeeded", "data": {"payment_id": "pay_member"}})
    assert (await client.post("/billing/webhook", content=raw, headers=signature)).status_code == 200
    assert (await client.get("/billing", headers=headers)).json()["available_aed"] == 10
    assert (await client.get("/billing", headers=owner_headers)).json()["available_aed"] == 10

    async def rejected(request):
        return httpx.Response(429, json={"error": {"code": "rate_limit_exceeded"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(rejected)) as llm.client:
        with pytest.raises(ProviderFailure):
            await llm.complete(system="test", user="hello", role="voice", max_tokens=100, usage=Usage())
    assert (await client.get("/billing", headers=headers)).json()["available_aed"] == 10
