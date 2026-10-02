"""Usage metering: every job records tokens and cost; runs on the platform key debit credits."""
from __future__ import annotations

from app.db.session import session_scope
from app.models import UsageEvent
from app.services.llm import Usage
from app.services.providers import Resolved
from app.services.quotas import ledger


async def record(org_id: str, sim_id: str | None, kind: str, usage: Usage, res: Resolved) -> int:
    credits = int(usage.calls) if res.metered else 0
    async with session_scope() as s:
        s.add(UsageEvent(org_id=org_id, simulation_id=sim_id, kind=kind, quantity=usage.calls, unit="llm_calls",
                         input_tokens=usage.input_tokens, output_tokens=usage.output_tokens, cost_usd=usage.cost(res.settings),
                         meta={"provider": res.settings.provider, "preset": res.settings.preset, "source": res.source,
                               "failed": usage.failed, "credits": credits}))
        if credits:
            await ledger(s, org_id, -credits, kind, sim_id)
    return credits
