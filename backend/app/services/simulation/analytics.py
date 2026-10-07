"""Turns a finished simulation into results: population projection, audience segments, attention,
spread, platform fit, psychology, discourse dynamics, A/B and the population lens."""
from __future__ import annotations

from collections import Counter

import numpy as np

from app.services.creator import audience_weights, creator_checks
from app.services.datapool.context import trend_alignment
from app.services.population.regions import AGE_BAND_LABELS, INTERESTS, PLATFORM_LABELS, PLATFORMS, REGIONS, STANCES

from . import cache, insights, projection


def group_label(r: int, band: int, male: int) -> str:
    return f"{'Men' if male else 'Women'} {AGE_BAND_LABELS[band]} · {REGIONS[r]['city']}"


# Share of followers who see a new post in the first hours, by platform (rough industry ranges; TikTok's
# For You feed shows new posts to a test pool beyond followers, hence the higher figure).
ORGANIC_REACH = {"tiktok": 0.25, "instagram": 0.08, "youtube": 0.10, "x": 0.05, "facebook": 0.05, "snapchat": 0.15, "linkedin": 0.08, "reddit": 0.10}


def real_world(casc: dict, followers: int | None, platform: str | None) -> dict | None:
    """Scale simulated reach to real people. Only possible when the creator's follower count is known: the
    model's first viewers are rescaled to the creator's realistic first audience, and spread is kept proportional."""
    if not followers or casc.get("seed_people", 0) <= 0:
        return None
    rate = ORGANIC_REACH.get(platform or "", 0.10)
    first = followers * rate
    cap = sum(r.get("social_users_m", 0) for r in REGIONS) * 1e6
    runs = np.minimum(np.array(casc["people_runs"], dtype=np.float64) * first / casc["seed_people"], cap)
    return {"followers": int(followers), "organic_rate": rate, "first_viewers": round(first), "median": int(np.median(runs)),
            "population_status": "placeholder", "population_label": "estimate, source pending",
            "p10": int(np.percentile(runs, 10)), "p90": int(np.percentile(runs, 90)),
            "p_over_100k": round(float((runs >= 1e5).mean()), 3), "p_over_1m": round(float((runs >= 1e6).mean()), 3),
            "method": f"Your {followers:,} followers × {rate:.0%} typical first-day organic reach on this platform = {first:,.0f} first "
                      "viewers; the simulated cascade's amplification is applied to them. Rough order of magnitude, not a forecast."}


def finalize(e) -> dict:
    pop = e.pop
    mask = pop.mask(e.audience)
    aud = np.flatnonzero(mask)
    if e.audience.get("follower_split"):
        w, _ = audience_weights(pop, aud, e.audience["follower_split"])
        # Population summaries reflect the creator's marginals, rather than generic population counts.
        aud = np.random.default_rng(e.seed + 77).choice(aud, aud.size, replace=True, p=w)
    voices = [a for a in e.agents.values() if a.kind == "voice" and a.reaction and "score" in a.reaction]
    by_idx = {int(a.ref[2:]): a for a in voices}
    ids = e.ids0
    # final surface: post-simulation opinion replaces the first-exposure score
    Yf = e.Y0.copy()
    Yf[:, 0] = [by_idx[int(i)].opinion for i in ids]
    surface = projection.fit(e.X0, Yf, e.targets, e.seed)
    surface.history = getattr(e, "history", None)
    P = projection.project_population(pop, surface, e.topic_vec, e.platform_key)
    cache.put(e.sim_id, {"A": P}, mask)
    sc = P[aud, 0].astype(np.float32)
    share = P[aud, 1].astype(np.float32)
    rs = np.random.default_rng(e.seed + 3)
    samp = rs.choice(aud, min(30000, aud.size), replace=False)
    lo, hi = projection.bootstrap_mean(e.X0, Yf[:, 0], projection.design(pop, samp, e.topic_vec, e.platform_key, surface.history), e.seed)
    confidence = min((x.get("confidence", 0) for x in pop.provenance.get("attribute_confidence", {}).values()), default=0)
    widening = (1 - confidence) * .5 + sum(x.get("uncertainty_widening", 0) for x in pop.provenance.get("conflicts", []))
    lo, hi = max(0, lo - widening), min(10, hi + widening)
    res: dict = {"seed": e.seed}
    res["population_provenance"] = pop.provenance
    res["population_version"] = pop.version
    res["population_uncertainty"] = {"additional_half_width": widening, "method": "Explicit heuristic widening for placeholder coverage and source conflicts; not a measured error bound"}
    memory = e.cfg.get("agent_memory", {})
    res["agent_memory"] = {key: memory.get(key) for key in ("fresh", "returning", "voice", "recalled", "requested_share", "achieved_share", "shortfall", "snapshot_at", "label")}
    res["memory_first_impressions"] = {variant: {"with_memory": round(float(np.mean([r["score"] for r in reactions])), 3),
        "fresh": round(float(np.mean([r["fresh_score"] for r in reactions])), 3) if all("fresh_score" in r for r in reactions) else None,
        "method": "Paired deterministic dry-run scores" if all("fresh_score" in r for r in reactions) else "Use explicit Fresh audience run history; no extra model calls"}
        for variant, reactions in {"A": [a.reaction for a in voices], "B": [a.reaction["B"] for a in voices if a.reaction.get("B")]}.items() if reactions}
    init_scores = np.array([by_idx[int(i)].initial for i in ids])
    final_scores = Yf[:, 0]
    res["audience"] = {"size": int(aud.size), "population": int(pop.n), "filters": e.audience, "voice_n": len(voices),
                       "stakeholders": sum(1 for a in e.agents.values() if a.kind == "stakeholder"),
                       "crowd_n": int(getattr(e, "crowd_idx", np.array([])).size),
                       "regions": [{"code": REGIONS[r]["code"], "name": REGIONS[r]["name"], "n": int(c)}
                                   for r, c in enumerate(np.bincount(pop.region[aud].astype(np.int64), minlength=len(REGIONS))) if c]}
    res["score"] = {"mean": round(float(sc.mean()), 2), "low": round(lo, 2), "high": round(hi, 2), "median": round(float(np.median(sc)), 2),
                    "std": round(float(sc.std()), 2), "hist": np.histogram(sc, bins=10, range=(0, 10))[0].tolist(),
                    "first_impression": round(float(init_scores.mean()), 2), "after_discussion": round(float(final_scores.mean()), 2),
                    "crowd_first": round(float(e.c_op0.mean()), 2) if getattr(e, "c_op0", None) is not None else None,
                    "crowd_final": round(float(e.c_op.mean()), 2) if getattr(e, "c_op", None) is not None else None,
                    "positive": round(float((sc >= 6.5).mean()), 3), "negative": round(float((sc < 4).mean()), 3),
                    "method": "Projected post-discussion opinion; bootstrap interval from 150 refits, widened for weak population evidence. Source uncertainty is a labelled heuristic, not a measured accuracy guarantee."}
    res["model"] = {"r2": dict(zip(surface.targets[:6], surface.r2[:6])), "features": int(e.X0.shape[1]), "lambda": surface.lam,
                    "voice_n": int(ids.size)}

    # segments ----------------------------------------------------------------------------------------
    reg, band, male, stance = (pop.region[aud].astype(np.int64), pop.age_band[aud].astype(np.int64), pop.male[aud].astype(np.int64),
                               pop.stance[aud].astype(np.int64))
    tm = (pop.interests[aud].astype(np.float32) @ e.topic_vec) * len(INTERESTS)
    vreg, vband, vmale, vst = (pop.region[ids].astype(np.int64), pop.age_band[ids].astype(np.int64), pop.male[ids].astype(np.int64),
                               pop.stance[ids].astype(np.int64))
    n_aud = aud.size

    def gstats(keys, vkeys, nk, labeler):
        cnt = np.bincount(keys, minlength=nk)
        ss, sh, tt = (np.bincount(keys, weights=w, minlength=nk) for w in (sc, share, tm))
        vc = np.bincount(vkeys, minlength=nk)
        return [{"key": int(k), "label": labeler(int(k)), "n": int(cnt[k]), "share_of_audience": round(float(cnt[k] / n_aud), 4),
                 "score": round(float(ss[k] / cnt[k]), 2), "would_share": round(float(sh[k] / cnt[k]), 3),
                 "topic_interest": round(float(tt[k] / cnt[k]), 2), "voice_n": int(vc[k])} for k in np.flatnonzero(cnt)]

    res["groups"] = {"region": gstats(reg, vreg, len(REGIONS), lambda k: REGIONS[k]["name"]),
                     "age": gstats(band, vband, 5, lambda k: AGE_BAND_LABELS[k]),
                     "gender": gstats(male, vmale, 2, lambda k: ["Women", "Men"][k]),
                     "stance": gstats(stance, vst, len(STANCES), lambda k: STANCES[k])}
    from app.services.population.uae import EMIRATES
    ae_aud, ae_voice = aud[reg == 0], ids[vreg == 0]
    if ae_aud.size:
        # Dedicated emirate segments retain real row counts; country AE remains the compatible union.
        emirate_rows = []
        for k, (code, label) in enumerate(EMIRATES.items()):
            members = ae_aud[pop.uae["residence_emirate"][ae_aud] == k]
            if members.size:
                values = P[members, 0].astype(np.float32)
                score = float(values.mean())
                emirate_rows.append({"key": code, "label": label, "n": int(members.size), "score": round(score, 2),
                    "low": max(0, score - widening), "high": min(10, score + widening), "population_status": pop.provenance["status"],
                    "voice_n": int((pop.uae["residence_emirate"][ae_voice] == k).sum())})
        res["groups"]["emirate"] = emirate_rows
    ikey = (reg * 5 + band) * 2 + male
    vikey = (vreg * 5 + vband) * 2 + vmale
    inter = gstats(ikey, vikey, len(REGIONS) * 10, lambda k: group_label(k // 10, (k // 2) % 5, k % 2))
    by_key: dict[int, list] = {}
    for i, k in zip(ids, vikey):
        by_key.setdefault(int(k), []).append(by_idx[int(i)])

    def evidence(g):
        vs = by_key.get(g["key"], [])
        if not vs:
            return None
        a = min(vs, key=lambda a: abs(a.opinion - g["score"]))
        return {"agent": a.ref, "name": a.name, "quote": a.reaction["quote"], "score": a.opinion, "objection": a.reaction.get("objection", "")}

    elig = [g for g in inter if g["share_of_audience"] >= 0.005 and g["voice_n"] >= 2] or [g for g in inter if g["voice_n"] >= 1]
    winners = sorted(elig, key=lambda g: -g["score"])[:3]
    losers = [g for g in sorted(elig, key=lambda g: g["score"]) if g not in winners][:3]
    shown = {g["key"] for g in winners + losers}
    opps = sorted([g for g in elig if g["key"] not in shown and g["topic_interest"] >= float(tm.mean()) and g["score"] < res["score"]["mean"] - 0.3],
                  key=lambda g: -g["share_of_audience"] * (res["score"]["mean"] - g["score"]))[:3]
    for g in winners + losers + opps:
        g["evidence"] = evidence(g)
    for g in opps:
        objs = Counter(a.reaction["objection"].lower() for a in by_key.get(g["key"], []) if a.reaction.get("objection"))
        g["objection"] = objs.most_common(1)[0][0] if objs else ""
        g["gap"] = round(res["score"]["mean"] - g["score"], 2)
    res["winners"], res["losers"], res["opportunities"] = winners, losers, opps
    res["intersections"] = sorted(inter, key=lambda g: -g["n"])[:60]

    # attention ---------------------------------------------------------------------------------------
    segcols = [k for k, t in enumerate(surface.targets) if t.startswith("seg")]
    E = P[aud][:, segcols].astype(np.float32)
    ret = np.cumprod(E, 1)
    em, rm = E.mean(0), ret.mean(0)
    votes = Counter(a.reaction["drop_segment"] for a in voices if a.reaction.get("drop_segment"))
    segs = []
    for k, s in enumerate(e.card["segments"]):
        prev = 1.0 if k == 0 else float(rm[k - 1])
        segs.append({"i": k, "label": s.get("label", f"Segment {k + 1}"), "start": s.get("start"), "end": s.get("end"), "text": s["text"][:500],
                     "note": s.get("note", ""), "engagement": round(float(em[k]), 3), "retention": round(float(rm[k]), 3),
                     "loss": round(prev - float(rm[k]), 3), "drop_votes": int(votes.get(k + 1, 0)),
                     "drop_quotes": [{"agent": a.ref, "name": a.name, "quote": a.reaction["quote"]} for a in voices
                                     if a.reaction.get("drop_segment") == k + 1][:2]})
    rows = [{"label": "Whole audience", "values": em.round(3).tolist(), "n": int(n_aud)}]
    for k in np.unique(reg):
        rows.append({"label": REGIONS[k]["name"], "values": E[reg == k].mean(0).round(3).tolist(), "n": int((reg == k).sum())})
    for k in np.unique(band):
        rows.append({"label": f"Age {AGE_BAND_LABELS[k]}", "values": E[band == k].mean(0).round(3).tolist(), "n": int((band == k).sum())})
    for k in np.unique(stance):
        rows.append({"label": STANCES[k].capitalize(), "values": E[stance == k].mean(0).round(3).tolist(), "n": int((stance == k).sum())})
    res["heatmap"] = {"segments": segs, "rows": rows, "timed": bool(e.card.get("timed")), "duration": e.card.get("duration"),
                      "completion": round(float(rm[-1]), 3) if segs else None,
                      "worst": max(segs, key=lambda s: s["loss"])["i"] if segs else None,
                      "peak": max(segs, key=lambda s: s["engagement"])["i"] if segs else None}

    # spread ------------------------------------------------------------------------------------------
    exposures = max(1, getattr(e, "c_exposed_creator", 0))
    emp = getattr(e, "c_reposts_creator", 0) / exposures
    model_rate = float(share.mean()) * 0.15
    boost = float(np.clip(emp / model_rate, 0.5, 3.0)) if model_rate > 0 and exposures > 50 else 1.0
    if e.card.get("format_key") == "short_video" and e.platform_key in ("tiktok", "instagram", "youtube"):
        boost *= 1 + float(np.mean([a.reaction.get("rewatch_probability", 0) + a.reaction.get("stitch_duet_likelihood", 0) for a in voices]))
    casc = projection.cascade(pop, P[:, 1], aud, e.seed, boost=boost)
    casc["real_world"] = real_world(casc, getattr(e, "creator_followers", None), e.platform_key)
    fol = pop.followers_n[aud]
    top_dec = fol >= np.percentile(fol, 90)
    factors = {"emotional_resonance": float(P[aud, 4].astype(np.float32).mean()), "shareability": min(1.0, float(share.mean()) / 0.4),
               "novelty": float(P[aud, 5].astype(np.float32).mean()), "controversy": min(1.0, float(sc.std()) / 3.0),
               "influencer_appeal": float(sc[top_dec].mean()) / 10 if top_dec.any() else 0.0}
    res["trend"] = trend_alignment(e.card, e.snaps)
    factors["trend_alignment"] = float(res["trend"]["score"])
    weights = {"emotional_resonance": 0.2, "shareability": 0.25, "novelty": 0.15, "controversy": 0.1, "influencer_appeal": 0.15, "trend_alignment": 0.15}
    creator = [e.posts[pid] for pid in getattr(e, "creator", {}).values()]
    res["viral"] = {"score": round(1 + 9 * sum(weights[k] * factors[k] for k in factors), 1), "factors": {k: round(v, 3) for k, v in factors.items()},
                    "weights": weights, "raw": {"mean_share_intent": round(float(share.mean()), 3), "score_std": round(float(sc.std()), 2),
                                                "sim_repost_rate": round(emp, 4)},
                    "cascade": casc,
                    "in_simulation": {"views": int(sum(p.views for p in creator)), "likes": int(sum(p.likes + p.crowd_likes + p.up for p in creator)),
                                      "reposts": int(sum(p.reposts + p.crowd_reposts for p in creator)), "comments": int(sum(p.comments for p in creator)),
                                      "downvotes": int(sum(p.down for p in creator))},
                    "method": "Six 0-1 factors (weights shown). Cascade: independent cascade on the 1M follower graph, 8 runs, share "
                              "probability scaled by the repost rate the crowd actually showed in the simulation."}

    # platforms -----------------------------------------------------------------------------------------
    plats = []
    for p in PLATFORMS:
        u = pop.uses(p)[aud]
        if u.sum() >= 50:
            plats.append({"platform": p, "label": PLATFORM_LABELS[p], "users": int(u.sum()), "reach_share": round(float(u.mean()), 3),
                          "score": round(float(sc[u].mean()), 2), "would_share": round(float(share[u].mean()), 3),
                          "completion": round(float(ret[u, -1].mean()), 3) if segs else None})
    plats.sort(key=lambda x: -(x["score"] + 10 * x["would_share"]))
    cut = []
    if e.card.get("timed") and segs and segs[-1]["end"]:
        ends = [s["end"] for s in segs]
        for t in (15, 30, 60, 90):
            if t < ends[-1]:
                k = next(j for j, x in enumerate(ends) if x >= t)
                cut.append({"seconds": t, "still_watching": round(float(rm[k]), 3), "segment": k + 1})
    res["platforms"] = {"by_platform": plats, "length_check": cut, "target": e.platform_key}

    # psychology ------------------------------------------------------------------------------------------
    vr = [a.reaction for a in voices]
    emo = Counter(r["primary_emotion"] for r in vr)
    res["psychology"] = {
        "emotions": [{"emotion": k, "share": round(v / len(vr), 3), "mean_score": round(float(np.mean([r["score"] for r in vr if r["primary_emotion"] == k])), 2)}
                     for k, v in emo.most_common(8)],
        "drivers": [{"driver": k, "share": round(v / len(vr), 3)} for k, v in Counter(d for r in vr for d in r.get("drivers", [])).most_common(8)],
        "decision_modes": [{"mode": k, "share": round(v / len(vr), 3)} for k, v in Counter(r.get("decision_mode") or "unknown" for r in vr).most_common()],
        "objections": [{"objection": k, "n": v} for k, v in Counter(r["objection"].lower().strip(" .") for r in vr if r.get("objection")).most_common(8)],
        "sentiment": dict(Counter(r["sentiment"] for r in vr))}

    # discourse (the simulated social dynamics) ------------------------------------------------------------
    shift = final_scores - init_scores
    received = Counter()
    for p in e.posts.values():
        if p.author_ref in e.agents:
            received[p.author_ref] += p.likes + p.crowd_likes + p.up + 2 * (p.reposts + p.crowd_reposts) + 3 * p.comments
    leaders = []
    for ref, v in received.most_common(8):
        a = e.agents[ref]
        leaders.append({"agent": ref, "name": a.name, "handle": a.handle, "kind": a.kind, "region": a.region, "engagement": int(v),
                        "followers": a.followers, "opinion": a.opinion, "stance": a.persona.get("stance")})
    top_posts = sorted((p for p in e.posts.values() if p.kind in ("post", "comment", "quote", "external")),
                       key=lambda p: -(p.likes + p.crowd_likes + p.up - p.down + 2 * (p.reposts + p.crowd_reposts) + 3 * p.comments))[:12]
    res["discourse"] = {
        "actions": {f"{k[0]}:{k[1]}": v for k, v in e.counts.items()}, "posts": len(e.posts),
        "changed_mind": int((np.abs(shift) >= 1).sum()), "mean_shift": round(float(shift.mean()), 3),
        "polarization_before": round(float(init_scores.std()), 2), "polarization_after": round(float(final_scores.std()), 2),
        "shift_by_stance": {STANCES[k]: round(float(shift[vst == k].mean()), 2) for k in np.unique(vst)},
        "leaders": leaders,
        "top_posts": [{"id": p.id, "platform": p.platform, "kind": p.kind, "author": p.author_name, "author_ref": p.author_ref,
                       "content": p.content[:400], "round": p.round, **p.stats()} for p in top_posts],
        "events": [x for x in e.cfg["events"].get("scheduled", [])],
    }
    res["timeline"] = e.timeline
    res["agents"] = [{"ref": a.ref, "name": a.name, "handle": a.handle, "kind": a.kind, "region": a.region, "stance": a.persona.get("stance"),
                      "initial": a.initial, "final": a.opinion, "actions": a.actions, "followers": a.followers,
                      "age": a.persona.get("age"), "city": a.persona.get("city") or a.persona.get("region")} for a in e.agents.values()]

    # population lens ------------------------------------------------------------------------------------
    sp = rs.choice(aud, min(4000, aud.size), replace=False)
    res["population_sample"] = {"fields": ["id", "age", "score", "share", "region", "stance", "openness", "followers"],
                                "rows": np.stack([sp, pop.age[sp], P[sp, 0].astype(np.float32).round(2), P[sp, 1].astype(np.float32).round(3),
                                                  pop.region[sp], pop.stance[sp], pop.ocean[sp, 0].astype(np.float32).round(2),
                                                  pop.followers_n[sp]], 1).tolist(),
                                "regions": [r["code"] for r in REGIONS], "stances": STANCES}
    res["checks"] = {"hook": e.card.get("hook"), "readability": e.card.get("readability"), "sensitivity_flags": e.card.get("sensitivity_flags", []),
                     "claims": e.card.get("claims", []), "word_count": e.card.get("word_count")}

    # A/B ---------------------------------------------------------------------------------------------------
    models = {"A": surface.to_json()}
    if e.card_b:
        withb = [a for a in voices if (a.reaction or {}).get("B")]
        if len(withb) >= 5:
            d = np.array([a.reaction["B"]["score"] - a.reaction["score"] for a in withb])
            dl, dh, pb = projection.paired_bootstrap(d, e.seed)
            idsb = np.array([int(a.ref[2:]) for a in withb])
            nb = len(e.card_b["segments"])
            tb = ["score", "would_share", "would_comment", "would_follow", "emotion_intensity", "novelty"] + [f"seg{k}" for k in range(nb)]
            from app.services.content import topic_vector
            tvb = topic_vector(e.card_b.get("topics"))
            Xb = projection.design(pop, idsb, tvb, e.platform_key, getattr(e, "history", None), exact=True)
            Yb = np.array([[a.reaction["B"][t] if not t.startswith("seg") else a.reaction["B"]["segment_engagement"][int(t[3:])] for t in tb]
                           for a in withb], dtype=np.float64)
            sb = projection.fit(Xb, Yb, tb, e.seed + 1)
            sb.history = getattr(e, "history", None)
            Pb = projection.project_population(pop, sb, tvb, e.platform_key)
            cache.put(e.sim_id, {"B": Pb}, mask)
            models["B"] = sb.to_json()
            # compare first impressions (A's surface0 projection vs B) so both sides are measured the same way
            P0 = projection.project_population(pop, e.surface0, e.topic_vec, e.platform_key)
            a0, b0 = P0[aud, 0].astype(np.float32), Pb[aud, 0].astype(np.float32)
            segb = [k for k, t in enumerate(tb) if t.startswith("seg")]
            EB = Pb[aud][:, segb].astype(np.float32)
            rb = np.cumprod(EB, 1).mean(0)
            comp = lambda keys, labels: [{"label": labels(k), "a": round(float(a0[keys == k].mean()), 2), "b": round(float(b0[keys == k].mean()), 2)}  # noqa: E731
                                         for k in np.unique(keys)]
            res["ab"] = {"paired_n": len(withb), "mean_diff": round(float(d.mean()), 2), "diff_low": round(dl, 2), "diff_high": round(dh, 2),
                         "p_b_better": round(pb, 3), "winner": "B" if dl > 0 else "A" if dh < 0 else "tie",
                         "a": {"score": round(float(a0.mean()), 2), "would_share": round(float(P0[aud, 1].astype(np.float32).mean()), 3),
                               "completion": res["heatmap"]["completion"], "emotion": round(float(P0[aud, 4].astype(np.float32).mean()), 3),
                               "novelty": round(float(P0[aud, 5].astype(np.float32).mean()), 3),
                               "would_comment": round(float(P0[aud, 2].astype(np.float32).mean()), 3)},
                         "b": {"score": round(float(b0.mean()), 2), "would_share": round(float(Pb[aud, 1].astype(np.float32).mean()), 3),
                               "completion": round(float(rb[-1]), 3) if rb.size else None, "emotion": round(float(Pb[aud, 4].astype(np.float32).mean()), 3),
                               "novelty": round(float(Pb[aud, 5].astype(np.float32).mean()), 3),
                               "would_comment": round(float(Pb[aud, 2].astype(np.float32).mean()), 3)},
                         "kind": getattr(e, "b_kind", "version"),
                         "by_region": comp(reg, lambda k: REGIONS[k]["name"]), "by_age": comp(band, lambda k: AGE_BAND_LABELS[k]),
                         "by_stance": comp(stance, lambda k: STANCES[k]),
                         "b_heatmap": [{"i": k, "label": s.get("label"), "engagement": round(float(EB[:, k].mean()), 3), "retention": round(float(rb[k]), 3)}
                                       for k, s in enumerate(e.card_b["segments"])],
                         "method": "Same voice agents gave first impressions of both versions; paired differences, 2000 bootstrap resamples. "
                                   "The social simulation runs on version A."}
    res["models"] = models
    res["topic_vector"] = e.topic_vec.tolist()
    res["topic_vectors"] = {"A": e.topic_vec.tolist()} | ({"B": tvb.tolist()} if "B" in models else {})
    res["platform"] = e.platform_key
    res["format"] = {"key": e.card.get("format_key"), "label": e.card.get("format_label")}
    res["b_kind"] = getattr(e, "b_kind", "version")
    res["creator"] = creator_checks(e, voices)
    return insights.add(e, res, aud)
