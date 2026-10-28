"""Spending limits: hard stops checked before every model call.

* Every job has a call cap (a runaway loop can never spend without bound, whoever's key it is).
* On the platform key (Kruvim's own key, metered in credits) a job also stops at the workspace's credit
  balance, and every call counts against a per-workspace and a platform-wide daily cap, so a beta
  cannot spend more of the owner's money in a day than KRUVIM_PLATFORM_DAILY_CALL_LIMIT allows."""
from __future__ import annotations

from app.core.config import settings
from app.core.ratelimit import count, peek
from app.services.llm import BudgetExceeded, Usage
from app.services.providers import Resolved

DAY = 86_400


async def platform_calls_today(org_id: str | None = None) -> dict:
    return {"platform": await peek("llm:platform", DAY), "org": await peek(f"llm:org:{org_id}", DAY) if org_id else None,
            "platform_limit": settings.platform_daily_call_limit, "org_limit": settings.org_daily_call_limit}


def _hook(org_id: str):
    async def before_call():
        org_n = await count(f"llm:org:{org_id}", DAY)
        if settings.org_daily_call_limit and org_n > settings.org_daily_call_limit:
            raise BudgetExceeded("Your workspace reached today's limit for Kruvim's shared model key. "
                                 "It resets at midnight UTC, or add your own API key in Settings.")
        total = await count("llm:platform", DAY)
        if settings.platform_daily_call_limit and total > settings.platform_daily_call_limit:
            raise BudgetExceeded("Kruvim's shared model key reached its daily limit. Try again tomorrow, "
                                 "or add your own API key in Settings.")
    return before_call


def guard(usage: Usage, org_id: str, res: Resolved, *, cap: int | None = None, balance: int | None = None) -> Usage:
    """Attach this job's limits to its Usage. `cap` is the job's own ceiling (e.g. 1.5x a run's estimate)."""
    limits = [settings.job_max_llm_calls]
    if cap is not None:
        limits.append(max(int(cap), 1))
    if res.metered:
        if balance is not None:
            limits.append(max(int(balance), 0))
        usage.before_call_hook = _hook(org_id)
    usage.max_calls = min(limits)
    usage.limit_message = ("This run used all the credits available to it and was stopped." if res.metered and balance is not None
                           and usage.max_calls == max(int(balance), 0)
                           else f"This step reached its safety limit of {usage.max_calls:,} model calls and was stopped.")
    return usage


def run_cap(estimate: int | None) -> int | None:
    if not estimate:
        return None
    return int(estimate * settings.run_call_cap_factor) + 50
