"""Reserve bounded request costs before network I/O; settle successful usage afterwards.

Uncertain failures keep their reservation: a timed-out request may still be billed upstream.
Reservations survive crashes. We never automatically release an uncertain provider charge.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, Decimal

from sqlalchemy import case, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.config import settings
from app.db.base import utcnow
from app.models import BillingAccount, BillingUsageWindow, SpendReservation
from app.services import billing
from app.services.llm.errors import BudgetPause

locks = defaultdict(asyncio.Lock)
PLATFORM_SCOPE = "platform"
LIMIT_PAUSES = ("ai_rate_limited", "platform_budget_exhausted")


def pause_state(message, code="api_budget_exhausted"):
    return {"code": code, "message": message, "actions": [
        {"id": "add_tokens", "label": "Open billing", "url": "/usage"}]}


def rates(llm, kwargs):
    model = llm.model_for("vision" if kwargs.get("images") else kwargs["role"])
    values = settings.billing_model_prices.get(model)
    if not values or any(k not in values or not 0 <= values[k] < 10000 for k in ("input", "output")):
        raise BudgetPause(pause_state("Kruvim's model pricing needs configuration. Please contact support.",
                                     "billing_model_unpriced"))
    # Cache reads/writes and provider fallbacks must not cost more than this configured input ceiling.
    return Decimal(str(values["input"])), Decimal(str(values["output"]))


def cost(inp, out, prices):
    usd = Decimal(inp) * prices[0] + Decimal(out) * prices[1]
    # USD per million tokens -> AED microdirhams: the factors of one million cancel.
    return int((usd * Decimal(str(settings.billing_usd_to_aed))).to_integral_value(rounding=ROUND_CEILING))


async def consume_window(s, scope, bucket, amount, limit):
    if amount > limit:
        return False
    window = BillingUsageWindow
    insert = sqlite_insert if settings.is_sqlite else pg_insert
    statement = insert(window).values(scope=scope, bucket=bucket, used=amount)
    statement = statement.on_conflict_do_update(
        index_elements=[window.scope],
        set_={"bucket": bucket, "used": case((window.bucket == bucket, window.used + amount), else_=amount)},
        where=(window.bucket < bucket) | ((window.bucket == bucket) & (window.used <= limit - amount)),
    ).returning(window.scope)
    return (await s.execute(statement)).scalar_one_or_none() is not None


async def reserve(org_id, amount):
    from app.services.token_budget import accounting_session
    async with locks[org_id]:
        async with accounting_session() as s:
            try:
                a = await billing.require_access(s, org_id)
            except Exception as exc:
                from app.core.errors import QuotaExceeded
                if isinstance(exc, QuotaExceeded):
                    raise BudgetPause(exc.details) from exc
                raise
            monthly = min(max(0, a.monthly_remaining), amount)
            topup = amount - monthly
            # Conditional arithmetic also protects SQLite/multiple API and worker processes.
            updated = (await s.execute(update(BillingAccount).where(
                BillingAccount.org_id == org_id,
                BillingAccount.monthly_remaining >= monthly,
                BillingAccount.topup_remaining >= topup,
                BillingAccount.monthly_remaining + BillingAccount.topup_remaining >= amount,
            ).values(monthly_remaining=BillingAccount.monthly_remaining - monthly,
                     topup_remaining=BillingAccount.topup_remaining - topup)
                .returning(BillingAccount.org_id))).scalar_one_or_none()
            if updated is None:
                raise BudgetPause(pause_state("Your included usage is running low. Buy more credits to continue this test."))
            now = utcnow()
            minute = int(now.timestamp() // 60)
            if not await consume_window(s, f"workspace:{org_id}", minute, 1, settings.billing_ai_calls_per_minute):
                reset = datetime.fromtimestamp((minute + 1) * 60, UTC)
                raise BudgetPause({"code": "ai_rate_limited", "reset_at": reset.isoformat(),
                                   "message": "This workspace is sending too many AI requests. Try again shortly."})
            month = now.year * 100 + now.month
            cap = billing.micros(settings.billing_platform_monthly_budget_aed)
            if not await consume_window(s, PLATFORM_SCOPE, month, amount, cap):
                reset = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=32)).replace(day=1)
                raise BudgetPause({"code": "platform_budget_exhausted", "reset_at": reset.isoformat(),
                                   "message": "Kruvim has reached its shared AI spending limit for this month."})
            reservation = SpendReservation(org_id=org_id, period_start=a.period_start, monthly=monthly, topup=topup,
                                           platform_bucket=month)
            s.add(reservation)
            await s.flush()
            return reservation.id


async def settle(reservation_id, actual):
    from app.services.token_budget import accounting_session
    async with accounting_session() as s:
        r = (await s.execute(update(SpendReservation).where(SpendReservation.id == reservation_id,
            SpendReservation.status == "reserved").values(actual=actual, status="settled")
            .returning(SpendReservation))).scalar_one_or_none()
        if r is None:
            return
        a = await billing.account(s, r.org_id, lock=True)
        reserved = r.monthly + r.topup
        refund = max(0, reserved - actual)
        # Monthly allowance is spent first, so unused purchased allowance is returned first.
        topup_refund = min(r.topup, refund)
        monthly_refund = refund - topup_refund if a.period_start == r.period_start else 0
        await s.execute(update(BillingAccount).where(BillingAccount.org_id == r.org_id).values(
            monthly_remaining=BillingAccount.monthly_remaining + monthly_refund,
            topup_remaining=BillingAccount.topup_remaining + topup_refund))
        if r.platform_bucket is not None and actual != reserved:
            await s.execute(update(BillingUsageWindow).where(BillingUsageWindow.scope == PLATFORM_SCOPE,
                BillingUsageWindow.bucket == r.platform_bucket).values(used=BillingUsageWindow.used + actual - reserved))
        if actual > reserved:
            # A provider violated the configured bound. Do not permit further spending.
            a.suspended = True


async def call(llm, fn, kwargs):
    org_id = llm.s.billing_org_id
    if not settings.billing_enabled or not org_id or llm.is_dry:
        return await fn(llm, **kwargs)
    from app.services.token_budget import accounting_session
    if not llm.s.billing_metered:
        async with accounting_session() as s:
            try:
                await billing.require_access(s, org_id)
            except Exception as exc:
                from app.core.errors import QuotaExceeded
                if isinstance(exc, QuotaExceeded):
                    raise BudgetPause(exc.details) from exc
                raise
        return await fn(llm, **kwargs)
    prices = rates(llm, kwargs)
    if kwargs.get("images"):
        # Image token accounting is model-specific; never guess a monetary bound.
        raise BudgetPause(pause_state("Platform image analysis is not enabled for this plan. Use a transcript or your own model key.",
                                     "billing_image_unpriced"))
    # UTF-8 byte count is a conservative text-token ceiling, plus protocol overhead.
    inp = len((kwargs["system"] + kwargs["user"]).encode("utf-8")) + 1024
    output = int(kwargs["max_tokens"])
    if llm.s.provider == "anthropic":
        # Anthropic currently permits server fallback and cache writes with different rates.
        raise BudgetPause(pause_state("Choose a priced OpenAI-compatible platform model to use included credits.",
                                     "billing_model_unpriced"))
    # Paid platform requests use one HTTP attempt. An uncertain timeout cannot be retried for free.
    amount = max(1, cost(inp, output, prices))
    reservation_id = await reserve(org_id, amount)
    from app.services.llm import Usage
    usage = Usage()  # Concurrent calls must never read each other's aggregate token counters.
    try:
        result = await fn(llm, **{**kwargs, "usage": usage})
    finally:
        original = kwargs["usage"]
        for role, row in usage.by_role.items():
            original.add(llm.name, row["model"], role, row["input"], row["cached"], row["output"], usage.seconds)
        original.failed += usage.failed
    if usage.calls and (usage.input_tokens or usage.output_tokens):
        await settle(reservation_id, cost(usage.input_tokens, usage.output_tokens, prices))
    # Missing usage retains the conservative reservation rather than granting free model use.
    return result
