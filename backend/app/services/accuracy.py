"""Auditable variant ranking accuracy; no workspace-identifying data in public reports."""
import math

from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.models import Simulation, SocialConnection, SocialPost


def summarize(pairs):
    correct = sum(pred == real for pred, real in pairs)
    n = len(pairs)
    interval = None
    if n:
        p, z = correct / n, 1.96
        center = (p + z*z/(2*n)) / (1 + z*z/n)
        margin = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
        interval = [round(100*(center-margin), 1), round(100*(center+margin), 1)]
    return {"n": n, "correct": correct, "accuracy_percent": round(100*correct/n, 1) if n else None,
            "confidence_interval_95": interval}


async def report(s, org_id=None):
    q = select(SocialPost, SocialConnection, Simulation).join(SocialConnection, SocialPost.connection_id == SocialConnection.id).join(
        Simulation, SocialPost.simulation_id == Simulation.id).where(SocialPost.org_id == SocialConnection.org_id,
                                                                    SocialPost.org_id == Simulation.org_id)
    if org_id:
        q = q.where(SocialPost.org_id == org_id)
    else:
        q = q.where(SocialConnection.share_accuracy.is_(True))
    rows = (await s.execute(q)).all()
    groups = {}
    for post, connection, sim in rows:
        groups.setdefault((post.org_id, post.simulation_id, connection.platform), {})[post.variant] = (post, sim)
    pairs, orgs, excluded = [], set(), 0
    for (oid, _, _), variants in groups.items():
        if set(variants) != {"A", "B"}:
            excluded += 1
            continue
        a, sim = variants["A"]
        b, _ = variants["B"]
        av, bv = a.metrics.get("views"), b.metrics.get("views")
        eligible = (a.metrics.get("window_eligible") and b.metrics.get("window_eligible")
                    and a.predicted_at == b.predicted_at and not a.prediction.get("dry", True) and not b.prediction.get("dry", True)
                    and a.prediction.get("winner") in ("A", "B") and a.prediction.get("b_kind") == "version"
                    and not a.last_error and not b.last_error and av is not None and bv is not None)
        if not eligible or av == bv or a.predicted_score == b.predicted_score:
            excluded += 1
            continue
        pairs.append((a.prediction["winner"], "A" if av > bv else "B"))
        orgs.add(oid)
    available = bool(org_id) or (len(pairs) >= settings.accuracy_min_tests and len(orgs) >= settings.accuracy_min_workspaces)
    data = summarize(pairs) if available else {"n": None, "correct": None, "accuracy_percent": None, "confidence_interval_95": None}
    return {**data, "available": available, "excluded": excluded if available else None, "generated_at": utcnow(),
            "method": "Frozen first-impression opinion ranks A/B variants against actual views observed 7–8 days after publication. "
                      "Both predictions must predate publication and come from the same run. One pair per simulation/platform. Ties, dry runs, competitors, "
                      "missing or late snapshots are excluded. Wilson 95% interval. Observational creator tests, not randomized experiments.",
            "reason": None if available else "Insufficient opted-in tests across independent workspaces; no accuracy claim yet."}
