"""Dodo checkout and fulfilment. Only verified server events grant paid access."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.core.errors import AppError, Conflict, Forbidden, QuotaExceeded
from app.db.base import utcnow
from app.models import BillingAccount, BillingEvent, BillingGrant, BillingOrder, BillingSeat, Membership, Organization

MICROS = 1_000_000
CREDIT_MICROS = 1_000  # One customer-facing usage credit = AED .001 of included API allowance.


def micros(aed) -> int:
    return int((Decimal(str(aed)) * MICROS).to_integral_value(rounding=ROUND_CEILING))


async def primary_seat_user(s, org_id):
    return (await s.execute(select(Membership.user_id).where(Membership.org_id == org_id)
        .order_by((Membership.role == "owner").desc(), Membership.created_at, Membership.user_id)
        .limit(1))).scalar_one_or_none()


async def seat_row(s, org_id, user_id):
    row = await s.get(BillingSeat, (org_id, user_id))
    if row is None:
        row = BillingSeat(org_id=org_id, user_id=user_id, monthly_remaining=0, topup_remaining=0)
        s.add(row)
        await s.flush()
    return row


async def claim_seat(s, a, user_id):
    """Called with the account locked. A seat can be assigned once per paid period."""
    member = await s.scalar(select(Membership.id).where(
        Membership.org_id == a.org_id, Membership.user_id == user_id))
    if not member:
        return None
    row = await seat_row(s, a.org_id, user_id)
    if a.topup_remaining:
        # Before seat billing, the workspace owner was the only person who could buy a pack.
        owner_id = await primary_seat_user(s, a.org_id)
        owner = await seat_row(s, a.org_id, owner_id)
        owner.topup_remaining += a.topup_remaining
        a.topup_remaining = 0
    if row.period_start != a.period_start:
        assigned = await s.scalar(select(func.count()).select_from(BillingSeat).where(
            BillingSeat.org_id == a.org_id, BillingSeat.period_start == a.period_start))
        vacant = a.seats - assigned
        if vacant > 0:
            row.period_start = a.period_start
            row.monthly_remaining = a.monthly_remaining // vacant
            a.monthly_remaining -= row.monthly_remaining
    return row


def available(a, seat):
    return seat.topup_remaining + (seat.monthly_remaining if seat.period_start == a.period_start else 0)


def insufficient(a, balance, required):
    display = "less than AED 0.01" if 0 < balance < MICROS // 100 else f"AED {Decimal(balance) / MICROS:.2f}"
    message = (f"Your seat has {display} of AI usage remaining. "
               "Top up or wait for your next successful renewal.")
    return QuotaExceeded(message, code="api_budget_exhausted", details={
        "code": "api_budget_exhausted", "message": message, "available_aed": balance / MICROS,
        "required_micros": required, "reset_at": a.period_end.isoformat() if a.period_end else None,
        "actions": [{"id": "add_tokens", "label": "Top up AI usage", "url": "/usage"}]})


def configured() -> bool:
    return bool(settings.dodo_api_key and settings.dodo_webhook_key and settings.dodo_business_id
                and settings.dodo_subscription_product_id and settings.dodo_topup_product_id)


def date(value) -> datetime | None:
    if not value:
        return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Payment dates must include a timezone")
    return result.astimezone(UTC)


async def account(s, org_id, *, lock=False):
    insert = sqlite_insert if settings.is_sqlite else pg_insert
    await s.execute(insert(BillingAccount).values(org_id=org_id, status="inactive", seats=1,
        monthly_remaining=0, topup_remaining=0, suspended=False).on_conflict_do_nothing(index_elements=["org_id"]))
    return (await s.execute(select(BillingAccount).where(BillingAccount.org_id == org_id)
        .with_for_update() if lock else select(BillingAccount).where(BillingAccount.org_id == org_id))).scalar_one()


def active(a: BillingAccount, now=None) -> bool:
    return bool(not a.suspended and a.status in ("active", "past_due") and a.period_end
                and a.period_end > (now or utcnow()))


def access_error(message="Subscribe to Kruvim to run simulations.", code="subscription_required"):
    return QuotaExceeded(message, code=code, details={"code": code, "message": message,
        "actions": [{"id": "billing", "label": "View billing", "url": "/usage"}]})


async def require_access(s, org_id):
    if not settings.billing_enabled:
        return None
    a = await account(s, org_id, lock=True)
    if not active(a):
        raise access_error("Your subscription needs attention. Open Billing to continue." if a.subscription_id
                           else "Subscribe to Kruvim to run simulations.")
    members = (await s.execute(select(func.count()).select_from(Membership).where(Membership.org_id == org_id))).scalar()
    if members > a.seats:
        raise access_error("This workspace has more members than paid seats. Update billing or remove extra members.",
                           "billing_seats_exceeded")
    return a


async def require_seat(s, org_id, user_id=None, *, minimum=0):
    a = await require_access(s, org_id)
    if a is None:
        return None, None
    if user_id is None:
        user_id = await primary_seat_user(s, org_id)
    seat = await claim_seat(s, a, user_id) if user_id else None
    if seat is None:
        raise access_error("This action needs a current workspace seat.", "billing_seat_required")
    balance = available(a, seat)
    if balance < minimum:
        raise insufficient(a, balance, minimum)
    return a, seat


async def status(s, org_id, user_id):
    a = await account(s, org_id, lock=True)
    member_count = (await s.execute(select(func.count()).select_from(Membership).where(Membership.org_id == org_id))).scalar()
    usable = active(a) and member_count <= a.seats
    seat = await claim_seat(s, a, user_id) if usable and user_id else None
    monthly = seat.monthly_remaining if seat and seat.period_start == a.period_start else 0
    purchased = seat.topup_remaining if seat else 0
    total = monthly + purchased
    return {"enabled": settings.billing_enabled, "configured": configured(), "provider": "dodo",
        "environment": settings.dodo_environment, "active": usable, "status": a.status,
        "review_required": a.suspended, "seats": a.seats, "members": member_count,
        "period_end": a.period_end, "can_manage": bool(a.customer_id),
        "monthly_price_aed": settings.billing_monthly_price_aed,
        "topup_price_aed": settings.billing_topup_price_aed,
        "monthly_credits": micros(settings.billing_monthly_budget_aed) // CREDIT_MICROS,
        "topup_credits": micros(settings.billing_topup_budget_aed) // CREDIT_MICROS,
        "monthly_remaining": monthly // CREDIT_MICROS,
        "purchased_remaining": purchased // CREDIT_MICROS,
        "available": total // CREDIT_MICROS,
        "monthly_allowance_aed": settings.billing_monthly_budget_aed,
        "topup_allowance_aed": settings.billing_topup_budget_aed,
        "monthly_remaining_aed": monthly / MICROS,
        "purchased_remaining_aed": purchased / MICROS,
        "available_aed": total / MICROS,
        "note": "" if configured() else "Checkout will be available once Kruvim's payment setup is complete."}


async def dodo(method, path, *, body=None, params=None, idempotency_key=None):
    if not settings.dodo_api_key:
        raise AppError("Payments are not configured yet.", status=503, code="billing_not_configured")
    if settings.dodo_environment not in ("test_mode", "live_mode"):
        raise AppError("Invalid payment environment.", status=503)
    host = "test" if settings.dodo_environment == "test_mode" else "live"
    headers = {"Authorization": "Bearer " + settings.dodo_api_key}
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            response = await client.request(method, f"https://{host}.dodopayments.com{path}",
                                            headers=headers, json=body, params=params)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError("Invalid response")
            return result
    except (httpx.HTTPError, ValueError):
        raise AppError("The payment service is unavailable. Please try again.", status=502, code="billing_unavailable")


def safe_url(value):
    parsed = urlparse(value or "")
    if parsed.scheme != "https" or not parsed.hostname or not (
            parsed.hostname == "dodopayments.com" or parsed.hostname.endswith(".dodopayments.com")):
        raise AppError("The payment service returned an invalid checkout link.", status=502)
    return value


async def checkout(s, p, kind, seats=1):
    if not settings.billing_enabled or not configured():
        raise AppError("Checkout will be available once payment setup is complete.", status=503, code="billing_not_configured")
    if p.via != "session":
        raise Forbidden("Sign in to purchase AI usage.")
    p.require("owner" if kind == "subscription" else "member")
    a = await account(s, p.org_id, lock=True)
    if kind == "subscription":
        if a.subscription_id and a.status not in ("cancelled", "expired", "failed"):
            raise Conflict("Manage your existing subscription in the billing portal.")
        members = (await s.execute(select(func.count()).select_from(Membership).where(Membership.org_id == p.org_id))).scalar()
        if seats < members:
            raise Conflict(f"Choose at least {members} seats for the current workspace members.")
        pending = (await s.execute(select(BillingOrder).where(BillingOrder.org_id == p.org_id,
            BillingOrder.kind == "subscription", BillingOrder.state == "pending",
            BillingOrder.created_at > utcnow() - timedelta(hours=24)).order_by(BillingOrder.created_at.desc())
            .limit(1))).scalar_one_or_none()
        if pending:
            if pending.checkout_url and pending.quantity == seats:
                return {"enabled": True, "url": safe_url(pending.checkout_url)}
            raise Conflict("A subscription checkout is already in progress. Complete it before starting another.")
        product_id = settings.dodo_subscription_product_id
        price = settings.billing_monthly_price_aed
        budget = micros(settings.billing_monthly_budget_aed) * seats
    else:
        await require_seat(s, p.org_id, p.user_id)
        seats = 1
        product_id = settings.dodo_topup_product_id
        price = settings.billing_topup_price_aed
        budget = micros(settings.billing_topup_budget_aed)
    # A dashboard misconfiguration must never silently charge a different advertised price.
    product = await dodo("GET", "/products/" + quote(product_id, safe=""))
    pricing = product.get("price") or {}
    expected_type = "recurring_price" if kind == "subscription" else "one_time_price"
    if (pricing.get("type") != expected_type or pricing.get("currency") != "AED"
            or pricing.get("price") != price * 100 or pricing.get("tax_inclusive") is not True
            or pricing.get("pay_what_you_want")
            or pricing.get("discount", 0) or pricing.get("discount_bps", 0)
            or pricing.get("purchasing_power_parity")
            or kind == "subscription" and (pricing.get("payment_frequency_interval") not in ("Month", "month")
                                           or pricing.get("payment_frequency_count") != 1)):
        raise AppError("The checkout price needs configuration. Please contact support.", status=503,
                       code="billing_product_mismatch")
    order = BillingOrder(org_id=p.org_id, kind=kind, product_id=product_id, quantity=seats, budget_micros=budget,
                         seat_user_id=p.user_id, price_minor=price * 100)
    s.add(order)
    await s.flush()
    # Persist the order before the external request: a fast webhook can arrive immediately.
    await s.commit()
    body = {"product_cart": [{"product_id": product_id, "quantity": seats}],
        "customer": {"customer_id": a.customer_id} if kind == "subscription" and a.customer_id
            else {"email": p.user.email, "name": p.user.name},
        "metadata": {"kruvim_order_id": order.id}, "billing_currency": "AED",
        "return_url": settings.public_app_url + "/usage?checkout=returned",
        "cancel_url": settings.public_app_url + "/usage?checkout=cancelled",
        "feature_flags": {"allow_discount_code": False, "allow_currency_selection": False}}
    if kind == "subscription":
        body["subscription_data"] = {"trial_period_days": 0}
    result = await dodo("POST", "/checkouts", body=body, idempotency_key="kruvim-" + order.id)
    order.session_id = result["session_id"]
    order.checkout_url = safe_url(result.get("checkout_url"))
    await s.commit()
    return {"enabled": True, "url": order.checkout_url}


def verify_webhook(raw: bytes, headers):
    try:
        event_id = headers["webhook-id"]
        stamp = headers["webhook-timestamp"]
        if len(event_id) > 160 or abs(time.time() - int(stamp)) > 300:
            raise ValueError("Expired signature")
        secret = settings.dodo_webhook_key.removeprefix("whsec_")
        key = base64.b64decode(secret, validate=True)
        signed = event_id.encode() + b"." + stamp.encode() + b"." + raw
        expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
        if not any(hmac.compare_digest(sig, "v1," + expected) for sig in headers["webhook-signature"].split()):
            raise ValueError("Invalid signature")
        payload = json.loads(raw)
        if not isinstance(payload, dict) or payload.get("business_id") != settings.dodo_business_id:
            raise ValueError("Wrong business")
        return event_id, payload
    except (KeyError, ValueError, TypeError):
        raise AppError("Invalid payment webhook.", status=401, code="invalid_webhook")


async def _order(s, data, subscription=None):
    order_id = (data.get("metadata") or {}).get("kruvim_order_id")
    if not order_id and subscription:
        order_id = (subscription.get("metadata") or {}).get("kruvim_order_id")
    return await s.get(BillingOrder, order_id, with_for_update=True) if order_id else None


async def _subscription(s, sub):
    order = await _order(s, sub)
    if not order or order.kind != "subscription" or sub.get("product_id") != order.product_id:
        return None
    a = await account(s, order.org_id, lock=True)
    sub_id = sub["subscription_id"]
    if a.subscription_id and a.subscription_id != sub_id and active(a):
        raise Conflict("A different subscription is already active for this workspace.")
    if a.subscription_id and a.subscription_id != sub_id and order.state == "fulfilled":
        return None  # A late event from an older subscription cannot replace its successor.
    if not 1 <= int(sub.get("quantity", 0)) <= 1000:
        raise ValueError("Invalid paid seat quantity")
    a.subscription_id = sub_id
    a.customer_id = sub["customer"]["customer_id"]
    a.status = sub["status"]
    return a, order


def verify_amount(payment, order, *, seats=1):
    total = int(payment.get("total_amount", 0))
    expected = (order.price_minor or (5000 if order.kind == "subscription" else 1000)) * seats
    # Older checkouts could add tax to the quoted amount.
    legacy_tax = int(payment.get("tax") or 0) if order.price_minor is None else 0
    if payment.get("currency") != "AED" or legacy_tax < 0 or total not in (expected, expected + legacy_tax):
        raise ValueError("Unexpected payment currency or amount")


async def _payment(s, payment, sub=None):
    if payment.get("status") != "succeeded" or payment.get("business_id") != settings.dodo_business_id:
        return
    if payment.get("refund_status") or payment.get("disputes") or any(
            r.get("status") == "succeeded" for r in payment.get("refunds", [])):
        return  # A refund/dispute can arrive before its original success event.
    payment_id = payment["payment_id"]
    grant_query = select(BillingGrant).where(BillingGrant.payment_id == payment_id)
    if (await s.execute(grant_query)).scalar_one_or_none():
        return
    sub_id = payment.get("subscription_id")
    if sub_id:
        linked = await _subscription(s, sub)
        if not linked:
            return
        a, order = linked
        # Both payment.succeeded and subscription.renewed can fulfill the same payment.
        # Check again after taking the subscription order lock.
        if (await s.execute(grant_query)).scalar_one_or_none():
            return
        periods = [p for p in payment.get("service_periods", []) if p.get("subscription_id") == sub_id]
        if payment.get("charge_type") not in ("new", "renewal") or not periods:
            return  # Plan-change/usage-only payments must not refresh the allowance.
        period = periods[0]
        start, end = date(period["starts_at"]), date(period["ends_at"])
        if not start or not end or end <= start:
            raise ValueError("Invalid service period")
        if Decimal(str(period.get("proration_factor", "1"))) != 1:
            raise ValueError("Expected a full service period")
        seats = int(sub["quantity"])
        if payment["charge_type"] == "new" and seats != order.quantity:
            raise ValueError("Initial paid seat quantity mismatch")
        verify_amount(payment, order, seats=seats)
        amount = 0
        if not a.period_start or start > a.period_start:
            a.seats = seats
            amount = micros(settings.billing_monthly_budget_aed) * seats
            a.period_start, a.period_end, a.monthly_remaining = start, end, amount
            members = (await s.scalars(select(Membership.user_id).where(Membership.org_id == a.org_id)
                .order_by((Membership.role == "owner").desc(), Membership.created_at, Membership.user_id)
                .limit(seats))).all()
            for user_id in members:
                seat = await seat_row(s, a.org_id, user_id)
                seat.period_start = start
                seat.monthly_remaining = micros(settings.billing_monthly_budget_aed)
                a.monthly_remaining -= seat.monthly_remaining
        org = await s.get(Organization, a.org_id)
        org.plan = "pro"
        org.settings = {**(org.settings or {}), "billing_seats": a.seats}
    else:
        order = await _order(s, payment)
        if not order or order.kind != "topup":
            return
        if order.state == "fulfilled":
            return
        cart = payment.get("product_cart") or []
        if len(cart) != 1 or cart[0].get("product_id") != order.product_id or cart[0].get("quantity") != 1:
            raise ValueError("Credit pack product mismatch")
        a = await account(s, order.org_id, lock=True)
        if not order.seat_user_id and a.customer_id != payment["customer"]["customer_id"]:
            raise ValueError("Credit pack customer mismatch")
        if (order.session_id and payment.get("checkout_session_id")
                and order.session_id != payment["checkout_session_id"]):
            raise ValueError("Credit pack checkout mismatch")
        verify_amount(payment, order)
        amount = order.budget_micros
        user_id = order.seat_user_id or await primary_seat_user(s, a.org_id)
        if user_id:
            seat = await seat_row(s, a.org_id, user_id)
            seat.topup_remaining += amount
        else:
            a.topup_remaining += amount
    order.state, order.payment_id = "fulfilled", order.payment_id or payment_id
    s.add(BillingGrant(org_id=a.org_id, payment_id=payment_id, kind=order.kind, amount=amount))


async def process_webhook(s, event_id, payload):
    insert = sqlite_insert if settings.is_sqlite else pg_insert
    kind, data = payload.get("type", ""), payload.get("data") or {}
    if await s.get(BillingEvent, event_id):
        return
    await s.commit()  # Release the read snapshot before Dodo I/O and the write transaction.
    payment, sub = None, None
    if kind == "payment.succeeded" or (kind == "subscription.renewed" and data.get("payment_id")):
        payment = await dodo("GET", "/payments/" + quote(data["payment_id"], safe=""))
        if payment.get("payment_id") != data["payment_id"]:
            raise ValueError("Payment id mismatch")
    sub_id = (payment or {}).get("subscription_id") or (data["subscription_id"] if kind.startswith("subscription.") else None)
    if sub_id:
        sub = await dodo("GET", "/subscriptions/" + quote(sub_id, safe=""))
        if sub.get("subscription_id") != sub_id:
            raise ValueError("Subscription id mismatch")
    inserted = (await s.execute(insert(BillingEvent).values(id=event_id, kind=kind)
        .on_conflict_do_nothing(index_elements=["id"]).returning(BillingEvent.id))).scalar_one_or_none()
    if not inserted:
        return
    if payment:
        await _payment(s, payment, sub)
    elif sub:
        await _subscription(s, sub)
    elif kind in ("refund.succeeded", "dispute.opened", "dispute.accepted", "dispute.lost") and data.get("payment_id"):
        grant = (await s.execute(select(BillingGrant).where(BillingGrant.payment_id == data["payment_id"])
                                 .with_for_update())).scalar_one_or_none()
        if grant and not grant.reversed:
            a = await account(s, grant.org_id, lock=True)
            # Stop spending until an operator reviews a refunded/disputed purchase.
            a.suspended, grant.reversed = True, True
    await s.commit()
