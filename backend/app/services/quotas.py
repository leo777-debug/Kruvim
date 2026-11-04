"""Plans, limits and the credit ledger.

Credits are the unit of LLM work: 1 credit ≈ one LLM agent turn. Organisations receive a monthly
grant from their plan. Purchasing credits (payment wall) is intentionally not wired yet; the ledger
accepts `purchase` entries when a payment provider is added."""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import QuotaExceeded
from app.db.base import utcnow
from app.models import CreditLedger, Organization, PlanAllowance, Simulation

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
for _name, _daily in [('free', 500), ('pro', 5000), ('business', 25000), ('enterprise', 100000)]:
    PLANS[_name]['daily_credits'] = _daily

# Native agent memory: bounds apply to every person in one workspace, including superseded rows.
for _name, _days, _cap in (("free", 30, 60), ("pro", 90, 60), ("business", 180, 60), ("enterprise", 365, 60)):
    PLANS[_name].update(memory_retention_days=_days, memory_cap_per_agent=_cap)


def plan(org: Organization) -> dict:
    base = PLANS.get(org.plan, PLANS['free'])
    from app.core.config import settings
    if settings.billing_enabled:
        seats = int((org.settings or {}).get('billing_seats', 1))
        return base | {'max_members': seats, 'monthly_credits': int(settings.billing_monthly_budget_aed * 1000) * seats}
    return base | {'daily_credits': (org.settings or {}).get('plan_allowance', {}).get('daily_credits', base['daily_credits'])}


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
    learning = rounds + 1
    memory = (voice + stake + 19) // 20
    return {"first_reactions": first, "social_turns": social, "report": report, "graph_learning": learning,
            "agent_memory": memory, "setup": 6, "total": first + social + learning + memory + report + 6}


async def balance(s: AsyncSession, org_id: str) -> int:
    org = await s.get(Organization, org_id)
    return int(org.credits_balance if org else 0)


async def ledger(s: AsyncSession, org_id: str, delta: int, reason: str, ref: str | None = None) -> int:
    org = await s.get(Organization, org_id, with_for_update=True)
    org.credits_balance = int(org.credits_balance or 0) + delta
    if reason in ('purchase', 'admin_adjust'):
        org.topup_balance = max(0, int(org.topup_balance or 0) + delta)
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


async def ensure_monthly_grant(s: AsyncSession, org: Organization, now=None) -> None:
    from app.core.config import settings
    if settings.billing_enabled:
        return  # Only a confirmed payment webhook refreshes paid allowances.
    now = now or utcnow()
    got = (await s.execute(select(func.count()).select_from(CreditLedger).where(and_(
        CreditLedger.org_id == org.id, CreditLedger.reason == "monthly_grant", CreditLedger.ref == now.strftime('%Y-%m'))))).scalar()
    if not got:
        await ledger(s, org.id, plan(org)["monthly_credits"], "monthly_grant", now.strftime("%Y-%m"))


async def allowance(s, org, now=None):
    """Daily cap on plan credits; purchased credits bypass the cap and never expire."""
    from app.core.config import settings
    if settings.billing_enabled:
        from app.services.billing import status
        paid = await status(s, org.id)
        return {'daily_limit': 0, 'daily_used': 0, 'daily_remaining': paid['available'],
            'monthly_remaining': paid['monthly_remaining'], 'topup_remaining': paid['purchased_remaining'],
            'available': paid['available'], 'reset_at': (paid['period_end'] or utcnow()).isoformat(),
            'timezone': 'Asia/Dubai', 'period': '', 'reason': 'monthly', 'warning': None}
    now = now or utcnow()
    override = await s.get(PlanAllowance, org.plan)
    if override:
        org.settings = {**(org.settings or {}), 'plan_allowance': {'daily_credits': override.daily_credits}}
    else:
        org.settings = {k: v for k, v in (org.settings or {}).items() if k != 'plan_allowance'}
    await ensure_monthly_grant(s, org, now)
    timezone = (org.settings or {}).get('timezone') or 'Asia/Dubai'
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        timezone, zone = 'Asia/Dubai', ZoneInfo('Asia/Dubai')
    local = now.astimezone(zone)
    day = local.date().isoformat()
    if org.daily_credit_day != day:
        org.daily_credit_day, org.daily_credits_used = day, 0
    limit = plan(org)['daily_credits']
    topup = min(max(0, org.topup_balance), max(0, org.credits_balance))
    monthly = max(0, org.credits_balance - topup)
    left = max(0, min(limit - org.daily_credits_used, monthly))
    reset = datetime.combine(local.date() + timedelta(days=1), time(), zone).astimezone(UTC)
    reason = 'daily' if limit - org.daily_credits_used <= monthly else 'monthly'
    if not monthly and not topup:
        reset = (now.replace(day=28, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=4)).replace(day=1)
        reason = 'monthly'
    return {'daily_limit': limit, 'daily_used': org.daily_credits_used, 'daily_remaining': left,
            'monthly_remaining': monthly, 'topup_remaining': topup, 'available': left + topup,
            'reset_at': reset.isoformat(), 'timezone': timezone, 'period': day, 'reason': reason,
            'warning': 95 if limit and org.daily_credits_used >= .95 * limit else 80 if limit and org.daily_credits_used >= .8 * limit else None}


def exhausted(state, needed=1, now=None):
    now = now or utcnow()
    minutes = max(1, int((datetime.fromisoformat(state['reset_at']) - now).total_seconds() / 60))
    duration = f'{minutes // 60} h {minutes % 60} min'
    if state['reason'] == 'monthly' and state['monthly_remaining'] == 0:
        message = f"Your plan's tokens are used up. Add more tokens, or come back when your monthly allowance resets in {duration}."
    else:
        message = f'Your tokens are used up for today. Add more tokens to keep going, or come back tomorrow. Your tokens reset in {duration}.'
    return {'code': 'workspace_tokens_exhausted', 'message': message,
        'estimate_message': f"This test needs about {needed:,} credits; you have {state['available']:,} left today.",
        'needed': needed, 'available': state['available'], 'reset_at': state['reset_at'],
        'actions': [{'id': 'add_tokens', 'label': 'Add more tokens', 'url': '/usage'},
                    {'id': 'remind', 'label': 'Remind me tomorrow', 'url': '/tokens/remind'}]}


async def check_tokens(s, org, needed=1, now=None):
    from app.core.config import settings
    if settings.billing_enabled:
        from app.services.billing import require_access
        await require_access(s, org.id)
        state = await allowance(s, org, now)
        if state['available'] <= 0:
            raise QuotaExceeded('Your usage credits are exhausted. Buy more credits to continue.',
                code='api_budget_exhausted', details={'code': 'api_budget_exhausted',
                'message': 'Your usage credits are exhausted. Buy more credits to continue.',
                'actions': [{'id': 'add_tokens', 'label': 'Buy credits', 'url': '/usage'}]})
        return state  # Per-request dollar reservations, not call counts, enforce the cap.
    state = await allowance(s, org, now)
    if state['available'] < needed:
        details = exhausted(state, needed, now)
        raise QuotaExceeded(details['message'], code=details['code'], details=details)
    return state


async def debit_call(s, org, amount=1):
    from app.core.config import settings
    if settings.billing_enabled:
        await check_tokens(s, org)
        return {'daily': 0, 'topup': 0, 'period': ''}
    state = await check_tokens(s, org, amount)
    daily = min(amount, state['daily_remaining'])
    topup = amount - daily
    org.daily_credits_used += daily
    org.topup_balance -= topup
    await ledger(s, org.id, -amount, 'llm_call_reserve')
    return {'daily': daily, 'topup': topup, 'period': state['period']}


async def refund_call(s, org, allocations):
    amount = allocations.get('daily', 0) + allocations.get('topup', 0)
    if not amount:
        return
    if org.daily_credit_day == allocations['period']:
        org.daily_credits_used = max(0, org.daily_credits_used - allocations.get('daily', 0))
    org.topup_balance += allocations.get('topup', 0)
    await ledger(s, org.id, amount, 'llm_call_refund')


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
        Simulation.org_id == org.id, Simulation.status.in_(RUNNING), Simulation.pause_state['code'].as_string().is_(None))))).scalar()
    if running >= max(p["max_concurrent"], 1):
        raise QuotaExceeded(f"Your plan runs {p['max_concurrent']} simulation(s) at a time. Wait for one to finish.", code="concurrency_limit")
    need = estimate_credits(cfg)["total"]
    if platform_key:   # only metered when Kruvim's own model key is used
        await check_tokens(s, org, need)
    return need
