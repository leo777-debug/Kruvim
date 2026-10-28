"""Spending limits: hard stops checked before every model call.

* Every job has a call cap, so a runaway loop can never spend without bound, whoever's key it is.
* On the platform key (Kruvim's own key, metered in credits) a job also stops at the workspace's credit balance,
  and every call counts against a per-workspace and a platform-wide daily cap.
* Workspace admins can set their own limits (Settings -> Spending limits) that apply to every key, their own
  included: model calls per month, dollars per month (needs model prices) and calls per member per day.

Counters live in Redis (shared by API replicas and workers); usage events in the database remain the record."""
from __future__ import annotations

from datetime import UTC, datetime

from app.core.config import settings
from app.core.ratelimit import add, count, peek, total
from app.services.llm import BudgetExceeded, Usage
from app.services.providers import Resolved

DAY = 86_400
MONTH_TTL = 40 * DAY
LIMIT_KEYS = ("monthly_calls", "monthly_usd", "member_daily_calls")


def _month() -> str:
    return datetime.now(UTC).strftime("%Y%m")


def _day() -> str:
    return datetime.now(UTC).strftime("%Y%m%d")


def org_limits(org) -> dict:
    saved = ((getattr(org, "settings", None) or {}).get("limits") or {}) if org is not None else {}
    return {k: saved.get(k) for k in LIMIT_KEYS}


async def usage_now(org_id: str, user_id: str | None = None) -> dict:
    return {"month_calls": await total(f"llm:orgm:{org_id}:{_month()}"),
            "month_usd": round(await total(f"llm:orgusd:{org_id}:{_month()}") / 1e6, 4),
            "member_today_calls": await total(f"llm:user:{user_id}:{_day()}") if user_id else None}


async def platform_calls_today(org_id: str | None = None) -> dict:
    return {"platform": await peek("llm:platform", DAY), "org": await peek(f"llm:org:{org_id}", DAY) if org_id else None,
            "platform_limit": settings.platform_daily_call_limit, "org_limit": settings.org_daily_call_limit}


async def flush(org_id: str, usage: Usage, res: Resolved) -> None:
    """Add the dollars spent since the last check to the workspace's monthly total."""
    cost = usage.cost(res.settings)
    if cost is None:
        return
    delta = int(round((cost - usage.billed_usd) * 1e6))
    if delta > 0:
        usage.billed_usd = cost
        await add(f"llm:orgusd:{org_id}:{_month()}", delta, MONTH_TTL)


def _hook(org_id: str, res: Resolved, usage: Usage, limits: dict, user_id: str | None):
    async def before_call():
        if res.metered:
            org_n = await count(f"llm:org:{org_id}", DAY)
            if settings.org_daily_call_limit and org_n > settings.org_daily_call_limit:
                raise BudgetExceeded("Your workspace reached today's limit for Kruvim's shared model key. "
                                     "It resets at midnight UTC, or add your own API key in Settings.")
            all_n = await count("llm:platform", DAY)
            if settings.platform_daily_call_limit and all_n > settings.platform_daily_call_limit:
                raise BudgetExceeded("Kruvim's shared model key reached its daily limit. Try again tomorrow, "
                                     "or add your own API key in Settings.")
        await flush(org_id, usage, res)
        if limits.get("monthly_usd") and await total(f"llm:orgusd:{org_id}:{_month()}") >= limits["monthly_usd"] * 1e6:
            raise BudgetExceeded(f"Your workspace reached its monthly spending limit of ${limits['monthly_usd']:,.2f}. "
                                 "An admin can raise it in Settings, Spending limits.")
        month_n = await add(f"llm:orgm:{org_id}:{_month()}", 1, MONTH_TTL)
        if limits.get("monthly_calls") and month_n > limits["monthly_calls"]:
            raise BudgetExceeded(f"Your workspace reached its monthly limit of {limits['monthly_calls']:,} model calls. "
                                 "An admin can raise it in Settings, Spending limits.")
        if user_id:
            day_n = await add(f"llm:user:{user_id}:{_day()}", 1, 2 * DAY)
            if limits.get("member_daily_calls") and day_n > limits["member_daily_calls"]:
                raise BudgetExceeded(f"You reached today's limit of {limits['member_daily_calls']:,} model calls per member. "
                                     "It resets at midnight UTC.")
    return before_call


def guard(usage: Usage, org_id: str, res: Resolved, *, cap: int | None = None, balance: int | None = None,
          limits: dict | None = None, user_id: str | None = None) -> Usage:
    """Attach this job's limits to its Usage. `cap` is the job's own ceiling (e.g. 1.5x a run's estimate)."""
    ceilings = [settings.job_max_llm_calls]
    if cap is not None:
        ceilings.append(max(int(cap), 1))
    if res.metered and balance is not None:
        ceilings.append(max(int(balance), 0))
    usage.max_calls = min(ceilings)
    usage.limit_message = ("This run used all the credits available to it and was stopped." if res.metered and balance is not None
                           and usage.max_calls == max(int(balance), 0)
                           else f"This step reached its safety limit of {usage.max_calls:,} model calls and was stopped.")
    if res.settings.provider != "dryrun":
        usage.before_call_hook = _hook(org_id, res, usage, limits or {}, user_id)
    return usage


async def check_room(org, user_id: str | None, needed_calls: int) -> None:
    """Refuse to start work that would certainly cross a workspace limit (the hard stop still guards the rest)."""
    from app.core.errors import QuotaExceeded
    limits, used = org_limits(org), await usage_now(org.id, user_id)
    if limits["monthly_usd"] and used["month_usd"] >= limits["monthly_usd"]:
        raise QuotaExceeded(f"Your workspace reached its monthly spending limit of ${limits['monthly_usd']:,.2f}.", code="limit_reached")
    if limits["monthly_calls"] and used["month_calls"] + needed_calls > limits["monthly_calls"]:
        left = max(limits["monthly_calls"] - used["month_calls"], 0)
        raise QuotaExceeded(f"This needs about {needed_calls:,} model calls; your workspace has {left:,} left this month.",
                            code="limit_reached", details={"needed": needed_calls, "left": left})
    if user_id and limits["member_daily_calls"] and (used["member_today_calls"] or 0) + needed_calls > limits["member_daily_calls"]:
        left = max(limits["member_daily_calls"] - (used["member_today_calls"] or 0), 0)
        raise QuotaExceeded(f"This needs about {needed_calls:,} model calls; you have {left:,} left today.",
                            code="limit_reached", details={"needed": needed_calls, "left": left})


def run_cap(estimate: int | None) -> int | None:
    if not estimate:
        return None
    return int(estimate * settings.run_call_cap_factor) + 50
