import hashlib
import math

import numpy as np
from sqlalchemy import select

from app.models import SimAgent


def returning_panel(pop, mask, baseline, returning_ids, share, rng):
    """Retain the baseline's exact region/gender/age quotas; prefer returners inside each."""
    baseline = np.asarray(baseline, dtype=np.int64)
    pool = np.flatnonzero(mask)
    returning = np.asarray(sorted(set(returning_ids)), dtype=np.int64)
    returning = returning[(returning >= 0) & (returning < pop.n)]
    returning = returning[mask[returning]]
    def keys(idx):
        emirate = np.where(pop.region[idx] == 0, pop.uae["residence_emirate"][idx] + 1, 0)
        return ((pop.region[idx].astype(int) * 5 + emirate) * 2 + pop.male[idx]) * 5 + pop.age_band[idx]
    groups, quotas = np.unique(keys(baseline), return_counts=True)
    desired = min(len(baseline), round(len(baseline) * share))
    raw = quotas * share
    allocation = np.floor(raw).astype(int)
    for i in np.argsort(-(raw - allocation), kind="stable")[:desired - int(allocation.sum())]:
        allocation[i] += 1
    out, actual = [], 0
    pool_keys = keys(pool)
    for group, count, requested in zip(groups, quotas, allocation, strict=True):
        members = pool[pool_keys == group]
        old = members[np.isin(members, returning)]
        fresh = members[~np.isin(members, returning)]
        n_old = min(int(requested), len(old))
        # Fill scarce fresh slots with returning people, documenting the achieved share.
        n_old = max(n_old, int(count) - len(fresh))
        n_new = int(count) - n_old
        out.extend(rng.choice(old, n_old, replace=False).tolist())
        out.extend(rng.choice(fresh, n_new, replace=False).tolist())
        actual += n_old
    result = np.asarray(out, dtype=np.int64)
    rng.shuffle(result)
    return result, {"requested_share": share, "returning": actual, "voice": len(baseline),
        "achieved_share": actual / max(1, len(baseline)), "available_returning": len(returning), "shortfall": max(0, desired - actual)}


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
