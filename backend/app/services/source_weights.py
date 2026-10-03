"""Source associations from opted-in frozen outcome pairs; not a causal source contribution."""
from sqlalchemy import select

from app.core.config import settings
from app.models import SocialConnection, SocialPost


def weights_from_pairs(pairs, minimum):
    total = {}
    for sources, correct in pairs:
        for source in set(sources):
            n, hits = total.get(source, (0, 0))
            total[source] = n + 1, hits + int(correct)
    return {source: {"n": n, "weight": round(.5 + hits/n, 3) if n >= minimum else 1.0,
                     "accuracy": round(hits/n, 3) if n >= minimum else None} for source, (n, hits) in total.items()}


async def learned_weights(s, niche=None):
    rows = (await s.execute(select(SocialPost).join(SocialConnection, SocialPost.connection_id == SocialConnection.id).where(
        SocialConnection.share_accuracy.is_(True), SocialPost.org_id == SocialConnection.org_id))).scalars().all()
    groups = {}
    for post in rows:
        if niche and post.prediction.get("niche") != niche:
            continue
        groups.setdefault((post.org_id, post.simulation_id), {})[post.variant] = post
    pairs, orgs = [], set()
    for (oid, _), variants in groups.items():
        if set(variants) != {"A", "B"}:
            continue
        a, b = variants["A"], variants["B"]
        av, bv = a.metrics.get("views"), b.metrics.get("views")
        if not (a.metrics.get("window_eligible") and b.metrics.get("window_eligible")) or av is None or bv is None or av == bv:
            continue
        if a.prediction.get("dry", True) or b.prediction.get("dry", True) or a.prediction.get("winner") not in ("A", "B"):
            continue
        if a.predicted_at != b.predicted_at or a.prediction.get("b_kind") != "version":
            continue
        pairs.append((a.prediction.get("sources", []), a.prediction["winner"] == ("A" if av > bv else "B")))
        orgs.add(oid)
    enough = len(orgs) >= settings.accuracy_min_workspaces
    return {"niche": niche, "sources": weights_from_pairs(pairs, settings.source_weight_min_tests) if enough else {},
            "minimum": settings.source_weight_min_tests, "method": "Association of including each source with actual A/B rank accuracy. "
            "Opt-in aggregates only; equal weights until sufficient tests across independent workspaces. Not a causal estimate."}
