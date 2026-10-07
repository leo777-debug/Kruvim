"""Decision-oriented outputs computed from a finished run: poll results, when to publish, and a ranked list of
changes to make (the "Fix it" panel). Impact numbers here are labelled estimates derived from the run's own
measurements; the way to measure a change is to re-test it (same agents see both versions)."""
from __future__ import annotations

from datetime import timedelta

import numpy as np

from app.services.population.regions import AGE_BAND_LABELS, REGIONS, STANCES, region


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


# ---- poll ------------------------------------------------------------------------------------------------------
def poll(e, aud: np.ndarray) -> dict | None:
    opts = e.card.get("poll_options") or []
    voices = [a for a in e.agents.values() if a.kind == "voice" and a.reaction and "poll_choice" in a.reaction]
    if not opts or not voices:
        return None
    pop = e.pop
    cell = lambda idx: (pop.region[idx].astype(np.int64) * 5 + pop.age_band[idx].astype(np.int64)) * 2 + pop.male[idx].astype(np.int64)  # noqa: E731
    ids = np.array([int(a.ref[2:]) for a in voices])
    aud_cells = np.bincount(cell(aud), minlength=len(REGIONS) * 10) / max(aud.size, 1)
    v_cells = cell(ids)
    v_share = np.bincount(v_cells, minlength=len(REGIONS) * 10) / len(ids)
    w = aud_cells[v_cells] / np.maximum(v_share[v_cells], 1e-9)          # post-stratify voices to the audience
    choice = np.array([a.reaction["poll_choice"] for a in voices])
    tot = float(w.sum())
    votes = [float(w[choice == k + 1].sum()) for k in range(len(opts))]
    voted = sum(votes)
    by = {}
    for name, keys, labels in (("region", pop.region[ids].astype(np.int64), [r["name"] for r in REGIONS]),
                               ("age", pop.age_band[ids].astype(np.int64), AGE_BAND_LABELS),
                               ("stance", pop.stance[ids].astype(np.int64), STANCES)):
        rows = []
        for k in np.unique(keys):
            m = (keys == k) & (choice > 0)
            if m.sum() >= 2:
                rows.append({"label": labels[k], "n": int(m.sum()),
                             "shares": [round(float((choice[m] == j + 1).mean()), 3) for j in range(len(opts))]})
        by[name] = rows
    lead = int(np.argmax(votes)) if voted else None
    return {"options": opts, "share_of_voters": [round(v / voted, 3) if voted else 0 for v in votes],
            "turnout": round(voted / tot, 3) if tot else 0, "voters_n": int((choice > 0).sum()), "voices_n": len(voices),
            "leader": lead, "by": by,
            "method": "Interviewed agents' votes, weighted so each region × age × gender cell counts as much as it does in the audience."}


# ---- timing ----------------------------------------------------------------------------------------------------
def timing(e, res: dict) -> dict:
    regs = [(region(r["code"]), r["n"]) for r in res["audience"]["regions"]]
    utc = np.zeros(24)
    for reg, n in regs:
        tz = int(round(reg["tz_offset"]))
        utc += n * np.array([reg["curve"][(h + tz) % 24] for h in range(24)])
    utc /= max(utc.max(), 1e-9)
    win = utc + np.roll(utc, -1)
    h0 = int(np.argmax(win))
    main = max(regs, key=lambda x: x[1])[0] if regs else region("AE")
    loc = lambda h, reg: int((h + round(reg["tz_offset"])) % 24)  # noqa: E731
    per_region = [{"code": reg["code"], "city": reg["city"], "best_local_hour": int(np.argmax(reg["curve"])),
                   "share": round(n / max(sum(x[1] for x in regs), 1), 3)} for reg, n in regs]
    upcoming = []
    for code, snap in (e.snaps or {}).items():
        for ev in snap.get("events") or []:
            d = ev.get("days_away")
            if d is not None and 0 <= d <= 21 and ev.get("name"):
                upcoming.append({"region": code, "name": ev["name"], "days_away": int(d)})
    upcoming = sorted({(u["name"], u["days_away"]): u for u in upcoming}.values(), key=lambda u: u["days_away"])[:6]
    peak = None
    tl = e.timeline or []
    if len(tl) > 1:
        tot = [sum((t.get("actions") or {}).values()) for t in tl]
        deltas = [tot[0]] + [b - a for a, b in zip(tot, tot[1:])]
        k = int(np.argmax(deltas))
        when = e.sim_time(tl[k]["round"]) + timedelta(hours=main["tz_offset"])
        peak = {"round": tl[k]["round"], "local_time": when.strftime("%a %H:%M"), "city": main["city"],
                "hours_after_publish": round(tl[k]["round"] * e.mpr / 60, 1)}
    return {"best_window_utc": [h0, (h0 + 2) % 24], "best_window_local": [loc(h0, main), loc(h0 + 2, main)], "city": main["city"],
            "per_region": per_region, "upcoming": upcoming, "peak_in_simulation": peak,
            "activity_utc": [round(float(x), 3) for x in utc],
            "method": "Hourly activity curves of each region in the audience, weighted by audience size; two-hour window with the "
                      "highest combined activity. Upcoming holidays come from the live calendar connector."}


# ---- recommendations ("Fix it") ---------------------------------------------------------------------------------
def recommendations(e, res: dict) -> list[dict]:
    recs: list[dict] = []
    hm = res.get("heatmap") or {}
    segs = hm.get("segments") or []
    final = hm.get("completion") or 0
    flags = (res.get("checks") or {}).get("sensitivity_flags") or []
    for f in flags[:2]:
        recs.append({"id": f"flag-{len(recs)}", "area": "Risk", "priority": 100, "title": "Review a sensitivity flag",
                     "detail": f, "evidence": "Flagged during content analysis.", "impact": None, "action": None})
    if segs and hm.get("timed") is not None:
        first = segs[0]
        if first["loss"] >= 0.10:
            gain = 0.5 * first["loss"] * (final / max(first["retention"], 1e-6))
            recs.append({"id": "hook", "area": "Opening", "priority": 90 * gain + 10, "title": "Strengthen the opening",
                         "detail": f"{_pct(first['loss'])} of the audience leaves during the first segment (\"{first['label']}\"). "
                                   "Lead with the payoff or the most surprising line.",
                         "evidence": "; ".join(q["quote"] for q in first.get("drop_quotes", [])[:2]) or None,
                         "impact": {"metric": "completion", "estimate": f"+{gain * 100:.0f} pts", "basis": "if half of the early leavers stay"},
                         "action": {"type": "retest"}})
        rest = [s for s in segs[1:] if s["loss"] >= 0.08]
        if rest:
            w = max(rest, key=lambda s: s["loss"])
            gain = 0.5 * w["loss"] * (final / max(w["retention"], 1e-6))
            recs.append({"id": f"seg-{w['i']}", "area": "Pacing", "priority": 80 * gain + 8, "title": f"Tighten segment {w['i'] + 1}",
                         "detail": f"\"{w['label']}\" loses {_pct(w['loss'])} of the remaining audience, the largest drop after the opening.",
                         "evidence": "; ".join(q["quote"] for q in w.get("drop_quotes", [])[:2]) or None,
                         "impact": {"metric": "completion", "estimate": f"+{gain * 100:.0f} pts", "basis": "if half of those viewers stay"},
                         "action": {"type": "retest"}})
        cuts = [c for c in (res.get("platforms") or {}).get("length_check", []) if c["still_watching"] >= 0.6]
        if final < 0.5 and cuts:
            c = cuts[-1]
            recs.append({"id": "length", "area": "Length", "priority": 40, "title": f"Consider a {c['seconds']}-second cut",
                         "detail": f"Only {_pct(final)} reach the end; {_pct(c['still_watching'])} are still watching at {c['seconds']} seconds.",
                         "evidence": None, "impact": {"metric": "completion", "estimate": f"{_pct(c['still_watching'])} at {c['seconds']}s",
                                                      "basis": "measured retention at that point"}, "action": {"type": "retest"}})
    objs = (res.get("psychology") or {}).get("objections") or []
    voice_n = max((res.get("audience") or {}).get("voice_n", 1), 1)
    if objs and objs[0]["n"] >= 2:
        o = objs[0]
        recs.append({"id": "objection", "area": "Message", "priority": 60 * o["n"] / voice_n + 5, "title": "Answer the most common objection",
                     "detail": f"\"{o['objection']}\" was raised by {o['n']} of {voice_n} interviewed agents. Address it directly or remove what triggers it.",
                     "evidence": None, "impact": {"metric": "opinion", "estimate": f"{o['n'] / voice_n * 100:.0f}% of agents affected", "basis": "share raising it"},
                     "action": {"type": "retest"}})
    for g in (res.get("opportunities") or [])[:1]:
        lift = g["gap"] * g["share_of_audience"] / 2
        recs.append({"id": "opportunity", "area": "Audience", "priority": 300 * lift + 4, "title": f"Win over {g['label']}",
                     "detail": f"Interested in the topic but scores {g['gap']:.1f} below average"
                               + (f"; their main objection: \"{g['objection']}\"." if g.get("objection") else "."),
                     "evidence": (g.get("evidence") or {}).get("quote"),
                     "impact": {"metric": "projected opinion", "estimate": f"+{lift:.2f}", "basis": "if half of the gap closes"},
                     "action": {"type": "retest"}})
    plats = (res.get("platforms") or {}).get("by_platform") or []
    target = next((p for p in plats if p["platform"] == (res.get("platforms") or {}).get("target")), None)
    if plats and target and plats[0]["platform"] != target["platform"] and plats[0]["score"] - target["score"] >= 0.25:
        b = plats[0]
        recs.append({"id": "platform", "area": "Distribution", "priority": 20 + 10 * (b["score"] - target["score"]),
                     "title": f"Lead with {b['label']}", "detail": f"Its users rate this {b['score']:.2f} against {target['score']:.2f} on {target['label']}.",
                     "evidence": None, "impact": {"metric": "opinion among users", "estimate": f"+{b['score'] - target['score']:.2f}",
                                                  "basis": "projected scores by platform"}, "action": None})
    share = ((res.get("viral") or {}).get("raw") or {}).get("mean_share_intent", 0)
    if share < 0.08:
        recs.append({"id": "share", "area": "Call to action", "priority": 25, "title": "Give people a reason to share",
                     "detail": f"Average share intent is {_pct(share)}. A tag-a-friend prompt, a challenge or a useful takeaway raises it.",
                     "evidence": None, "impact": None, "action": {"type": "retest"}})
    t = res.get("timing") or {}
    if t.get("best_window_local"):
        a, b = t["best_window_local"]
        up = t.get("upcoming") or []
        recs.append({"id": "timing", "area": "Timing", "priority": 15, "title": f"Publish {a:02d}:00–{b:02d}:00 {t['city']} time",
                     "detail": "Highest combined activity across the audience's regions." + (f" Coming up: {up[0]['name']} in {up[0]['days_away']} days." if up else ""),
                     "evidence": None, "impact": None, "action": {"type": "schedule"}})
    trend = res.get("trend") or {}
    hot = (e.cfg.get("events") or {}).get("hot_topics") or []
    if trend.get("score", 1) < 0.2 and hot:
        recs.append({"id": "trend", "area": "Relevance", "priority": 12, "title": "Connect to what people are talking about",
                     "detail": "Little overlap with current regional news and trends. Topics people link to this: " + ", ".join(hot[:4]) + ".",
                     "evidence": None, "impact": {"metric": "viral score", "estimate": f"up to +{0.15 * 9 * (1 - trend.get('score', 0)):.1f}",
                                                  "basis": "trend alignment is 15% of the viral score"}, "action": {"type": "retest"}})
    p = res.get("poll")
    if p and p["turnout"] < 0.4:
        recs.append({"id": "poll", "area": "Poll", "priority": 30, "title": "Make the poll easier to answer",
                     "detail": f"Only {_pct(p['turnout'])} of the audience would vote. Shorter options and a sharper question raise turnout.",
                     "evidence": None, "impact": None, "action": {"type": "retest"}})
    recs.sort(key=lambda r: -r["priority"])
    for r in recs:
        r["priority"] = round(float(r["priority"]), 2)
    return recs[:10]


def add(e, res: dict, aud: np.ndarray) -> dict:
    res["poll"] = poll(e, aud)
    res["timing"] = timing(e, res)
    res["recommendations"] = recommendations(e, res)
    return res
