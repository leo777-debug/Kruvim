"""Plans, limits and the credit ledger.

Credits are the unit of LLM work: 1 credit ≈ one LLM agent turn. Organisations receive a monthly
grant from their plan. Purchasing credits (payment wall) is intentionally not wired yet; the ledger
accepts `purchase` entries when a payment provider is added."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceeded
from app.models import CreditLedger, Organization, Simulation

PLANS = {
    "free": {"label": "Free", "monthly_credits": 2_000, "max_voice": 60, "max_crowd": 5_000, "max_hours": 24,
             "max_concurrent": 1, "max_members": 3, "byo_key": True},
    "pro": {"label": "Pro", "monthly_credits": 40_000, "max_voice": 300, "max_crowd": 25_000, "max_hours": 72,
            "max_concurrent": 3, "max_members": 10, "byo_key": True},
    "business": {"label": "Business", "monthly_credits": 200_000, "max_voice": 800, "max_crowd": 100_000, "max_hours": 168,
                 "max_concurrent": 10, "max_members": 50, "byo_key": True},
    "enterprise": {"label": "Enterprise", "monthly_credits": 1_000_000, "max_voice": 2_000, "max_crowd": 250_000, "max_hours": 336,
                   "max_concurrent": 50, "max_members": 10_000, "byo_key": True},
}
RUNNING = ("queued", "running", "paused")


def plan(org: Organization) -> dict:
    return PLANS.get(org.plan, PLANS["free"])


def estimate_credits(cfg: dict) -> dict:
    """Expected LLM calls for a simulation config (= credits)."""
    voice = int(cfg.get("agents", {}).get("voice", 0))
    stake = int(cfg.get("agents", {}).get("stakeholders", 0))
    rounds = int(cfg.get("time", {}).get("rounds", 0))
    act = float(cfg.get("time", {}).get("mean_activation", 0.3))
    variants = 2 if cfg.get("ab") else 1
    first = voice * variants
    social = int(round((voice + stake) * rounds * act))
    report = 24
    return {"first_reactions": first, "social_turns": social, "report": report, "setup": 6, "total": first + social + report + 6}


async def balance(s: AsyncSession, org_id: str) -> int:
    org = await s.get(Organization, org_id)
    return int(org.credits_balance if org else 0)


async def ledger(s: AsyncSession, org_id: str, delta: int, reason: str, ref: str | None = None) -> int:
    org = await s.get(Organization, org_id, with_for_update=True)
    org.credits_balance = int(org.credits_balance or 0) + delta
    s.add(CreditLedger(org_id=org_id, delta=delta, balance_after=org.credits_balance, reason=reason, ref=ref))
    return org.credits_balance


async def reserve(s: AsyncSession, org_id: str, amount: int, reason: str, ref: str) -> None:
    if not amount:
        return
    available = (await s.execute(update(Organization).where(Organization.id == org_id, Organization.credits_balance >= amount)
                                 .values(credits_balance=Organization.credits_balance - amount)
                                 .returning(Organization.credits_balance))).scalar_one_or_none()
    if available is None:
        raise QuotaExceeded("Insufficient credits for this survey.")
    s.add(CreditLedger(org_id=org_id, delta=-amount, balance_after=available, reason=reason, ref=ref))


async def ensure_monthly_grant(s: AsyncSession, org: Organization) -> None:
    now = datetime.now(UTC)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    got = (await s.execute(select(func.count()).select_from(CreditLedger).where(and_(
        CreditLedger.org_id == org.id, CreditLedger.reason == "monthly_grant", CreditLedger.created_at >= month_start)))).scalar()
    if not got:
        await ledger(s, org.id, plan(org)["monthly_credits"], "monthly_grant", now.strftime("%Y-%m"))


async def check_start(s: AsyncSession, org: Organization, cfg: dict, platform_key: bool) -> int:
    p = plan(org)
    a = cfg.get("agents", {})
    t = cfg.get("time", {})
    if int(a.get("voice", 0)) > p["max_voice"]:
        raise QuotaExceeded(f"Your plan allows up to {p['max_voice']} voice agents.")
    if int(a.get("crowd", 0)) > p["max_crowd"]:
        raise QuotaExceeded(f"Your plan allows up to {p['max_crowd']:,} crowd agents.")
    if float(t.get("hours", 0)) > p["max_hours"]:
        raise QuotaExceeded(f"Your plan allows simulations up to {p['max_hours']} simulated hours.")
    running = (await s.execute(select(func.count()).select_from(Simulation).where(and_(
        Simulation.org_id == org.id, Simulation.status.in_(RUNNING))))).scalar()
    if running >= max(p["max_concurrent"], 1):
        raise QuotaExceeded(f"Your plan runs {p['max_concurrent']} simulation(s) at a time. Wait for one to finish.", code="concurrency_limit")
    need = estimate_credits(cfg)["total"]
    if platform_key:   # only metered when Kruvim's own model key is used
        await ensure_monthly_grant(s, org)
        if org.credits_balance < need:
            raise QuotaExceeded(f"This run needs about {need:,} credits; your balance is {org.credits_balance:,}.",
                                details={"needed": need, "balance": org.credits_balance})
    return need
