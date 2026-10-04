"""Read-side queries over a finished simulation: slice deep-dives and agent detail (any of the 1M)."""
from __future__ import annotations

from collections import Counter

import numpy as np
from sqlalchemy import or_, select

from app.db.session import session_scope
from app.models import Action, ChatMessage, Post, SimAgent, Simulation
from app.services.population import get_population
from app.services.population.regions import EDUCATION, INTEREST_LABELS, INTERESTS, PLATFORM_LABELS, PLATFORMS, REGIONS, STANCES

from . import cache
from .projection import Surface, project_one


async def explore(sim: Simulation, filters: dict) -> dict | None:
    d = await cache.get(sim.id, sim.results, sim.audience)
    if not d:
        return None
    pop = await get_population()
    sub = d["mask"] & pop.mask(filters)
    idx = np.flatnonzero(sub)
    out = {"size": int(idx.size), "share_of_audience": round(float(idx.size / max(1, d["mask"].sum())), 4)}
    if idx.size == 0:
        return out
    P = d["preds"]["A"]
    m = Surface.from_json(sim.results["models"]["A"])
    sc = P[idx, 0].astype(np.float32)
    seg = [k for k, t in enumerate(m.targets) if t.startswith("seg")]
    E = P[idx][:, seg].astype(np.float32)
    ints = pop.interests[idx].astype(np.float32).mean(0)
    out.update({
        "score": round(float(sc.mean()), 2), "score_hist": np.histogram(sc, bins=10, range=(0, 10))[0].tolist(),
        "would_share": round(float(P[idx, 1].astype(np.float32).mean()), 3), "would_comment": round(float(P[idx, 2].astype(np.float32).mean()), 3),
        "engagement": E.mean(0).round(3).tolist(), "retention": np.cumprod(E, 1).mean(0).round(3).tolist(),
        "platforms": sorted([{"platform": PLATFORM_LABELS[p], "share": round(float(pop.uses(p)[idx].mean()), 3)} for p in PLATFORMS], key=lambda x: -x["share"]),
        "interests": [{"label": INTEREST_LABELS[INTERESTS[k]], "w": round(float(ints[k]), 3)} for k in np.argsort(-ints)[:6]],
        "stances": {s: round(float((pop.stance[idx] == k).mean()), 3) for k, s in enumerate(STANCES)},
        "education": {e: round(float((pop.education[idx] == k).mean()), 3) for k, e in enumerate(EDUCATION)},
        "attitudes": {a: round(float(pop.attitudes[idx, k].astype(np.float32).mean()), 3) for k, a in enumerate(["religiosity", "media_trust", "political_interest"])},
    })
    async with session_scope() as s:
        rows = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim.id, SimAgent.kind == "voice"))).scalars().all()
    voices = [r for r in rows if r.ref.startswith("p:") and sub[int(r.ref[2:])] and r.reaction]
    out["voice_n"] = len(voices)
    out["voice_mean"] = round(float(np.mean([(r.state or {}).get("opinion", r.reaction.get("score", 5)) for r in voices])), 2) if voices else None
    out["quotes"] = [{"agent": r.ref, "name": r.name, "score": (r.state or {}).get("opinion", r.reaction.get("score")), "quote": r.reaction.get("quote"),
                      "who": f"{r.persona.get('age')}, {r.persona.get('city')}, {r.persona.get('stance')}"} for r in voices[:8]]
    out["emotions"] = Counter(r.reaction.get("primary_emotion") for r in voices).most_common(6)
    out["objections"] = Counter(r.reaction.get("objection", "").lower() for r in voices if r.reaction.get("objection")).most_common(5)
    # when this slice is online (local time), weighted by where its members live
    counts = np.bincount(pop.region[idx].astype(np.int64), minlength=len(REGIONS))
    act = np.zeros(24)
    for k, n in enumerate(counts):
        if n:
            act += n * np.array(REGIONS[k]["curve"])
    top = np.argsort(-act)[:3]
    out["peak_hours_local"] = sorted(int(h) for h in top)
    out["activity_local"] = (act / max(act.max(), 1e-9)).round(3).tolist()
    out["trust"] = {"media_trust": out["attitudes"]["media_trust"],
                    "label": "high" if out["attitudes"]["media_trust"] >= 0.6 else "low" if out["attitudes"]["media_trust"] < 0.4 else "moderate"}
    out["recommendations"] = _slice_recs(out)
    if len(voices) < 5:
        out["caveat"] = f"Only {len(voices)} interviewed agents fall in this slice; the numbers are model projections with little direct evidence."
    return out


def _slice_recs(o: dict) -> list[str]:
    recs = []
    if o["platforms"]:
        recs.append(f"Reach them on {o['platforms'][0]['platform']}" + (f" and {o['platforms'][1]['platform']}" if len(o["platforms"]) > 1 else "") + ".")
    if o.get("peak_hours_local"):
        recs.append("They are most active around " + ", ".join(f"{h:02d}:00" for h in o["peak_hours_local"]) + " local time.")
    if o["trust"]["label"] == "low":
        recs.append("Media trust is low: show proof (results, sources, real people) rather than claims.")
    elif o["trust"]["label"] == "high":
        recs.append("Media trust is relatively high: credible sources and expert voices land well.")
    if o["attitudes"]["religiosity"] >= 0.65:
        recs.append("Faith matters to this group: keep timing, imagery and tone respectful of religious practice.")
    if o["interests"]:
        recs.append("Connect the message to " + ", ".join(i["label"] for i in o["interests"][:2]) + ", their strongest interests.")
    ret = o.get("retention") or []
    if ret and ret[-1] < 0.5:
        recs.append(f"Only {ret[-1] * 100:.0f}% of this group would finish it: front-load the key point.")
    if o.get("objections"):
        recs.append(f"Their main objection: \"{o['objections'][0][0]}\".")
    return recs


async def agent_detail(sim: Simulation, ref: str) -> dict | None:
    pop = await get_population()
    async with session_scope() as s:
        row = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim.id, SimAgent.ref == ref))).scalar_one_or_none()
        posts = (await s.execute(select(Post).where(Post.simulation_id == sim.id, Post.author_ref == ref).order_by(Post.id).limit(40))).scalars().all()
        acts = (await s.execute(select(Action).where(Action.simulation_id == sim.id, or_(Action.actor_ref == ref, Action.target_ref == ref))
                                .order_by(Action.id).limit(80))).scalars().all()
        chat = (await s.execute(select(ChatMessage).where(ChatMessage.simulation_id == sim.id, ChatMessage.target == ref)
                                .order_by(ChatMessage.id))).scalars().all()
    out: dict = {"ref": ref, "kind": "population"}
    if row is not None:
        out.update({"kind": row.kind, "name": row.name, "handle": row.handle, "region": row.region, "persona": row.persona, "config": row.config,
                    "reaction": row.reaction, "state": row.state, "followers": row.followers})
    elif ref.startswith("p:"):
        i = int(ref[2:])
        if not 0 <= i < pop.n:
            return None
        p = pop.persona(i)
        out.update({"name": p["name"], "handle": p["handle"], "region": p["region"], "persona": p, "followers": p["followers"]})
    else:
        return None
    if ref.startswith("p:") and sim.results.get("models"):
        i = int(ref[2:])
        m = Surface.from_json(sim.results["models"]["A"])
        pr = project_one(pop, m, np.array(sim.results["topic_vector"], np.float32), sim.results.get("platform"), i)
        out["projected"] = {"score": round(pr["score"], 1), "would_share": round(pr["would_share"], 3), "would_comment": round(pr["would_comment"], 3),
                            "emotion_intensity": round(pr["emotion_intensity"], 2),
                            "segment_engagement": [round(pr[t], 3) for t in m.targets if t.startswith("seg")]}
        out["in_audience"] = bool(pop.mask(sim.audience or {})[i])
    out["posts"] = [{"id": p.id, "platform": p.platform, "kind": p.kind, "content": p.content, "round": p.round, "parent_id": p.parent_id, "stats": p.stats}
                    for p in posts]
    out["actions"] = [{"round": a.round, "platform": a.platform, "action": a.action, "actor": a.actor_name, "actor_ref": a.actor_ref,
                       "content": a.content, "target_post": a.target_post_id, "target_ref": a.target_ref} for a in acts]
    out["chat"] = [{"role": c.role, "content": c.content, "at": c.created_at.isoformat()} for c in chat]
    from app.services.agent_memory import detail_memory
    out["long_term_memory"] = await detail_memory(sim, ref, out["persona"])
    return out
