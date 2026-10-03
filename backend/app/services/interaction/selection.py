import hashlib
import math

from sqlalchemy import select

from app.models import SimAgent


def summary_calls(n):
    return 0 if not n else 1 if n <= 50 else math.ceil(n / 50) + 1


async def select_respondents(s, sim_id, filters):
    q = select(SimAgent).where(SimAgent.simulation_id == sim_id)
    if filters.get("everyone"):
        q = q.where(SimAgent.kind == "voice")
    else:
        if filters.get("region"):
            q = q.where(SimAgent.region == filters["region"])
        if filters.get("kind"):
            q = q.where(SimAgent.kind == filters["kind"])
        if filters.get("stance"):
            q = q.where(SimAgent.persona["stance"].as_string() == filters["stance"])
    rows = (await s.execute(q)).scalars().all()
    rows.sort(key=lambda r: hashlib.sha256((sim_id + ":" + r.ref).encode()).hexdigest())
    n = len(rows) if filters.get("everyone") else min(len(rows), int(filters.get("n") or 12))
    return rows[:n], len(rows)


def survey_estimate(n, eligible, resolved, balance):
    summaries = summary_calls(n)
    calls = n + summaries
    dry = resolved.settings.provider == "dryrun"
    credits = calls if resolved.metered else 0
    maximum = n + summaries * 2 if resolved.metered else 0
    return {"respondents": n, "eligible": eligible, "model_calls": 0 if dry else calls, "summary_calls": summaries,
            "credits": credits, "max_credits": maximum, "balance": balance, "dry": dry, "metered": resolved.metered,
            "own_provider": not dry and not resolved.metered, "affordable": balance >= maximum}
