"""Dry-run policies: formula-driven stand-ins for every LLM decision. Output is tagged "[dry run]"
and is NOT a prediction - it exists so the full pipeline can be exercised without a model."""
from __future__ import annotations

import math

import numpy as np

TAG = "[dry run]"
STANCE_SHIFT = {"enthusiast": 1.0, "neutral": 0.0, "skeptic": -0.8, "contrarian": -1.5, "disengaged": -1.1}


def _sig(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def reaction(p: dict, tm: float, on_target: bool, card: dict, snap: dict | None, rng: np.random.Generator) -> dict:
    oc = p["ocean"]
    hook = (card.get("hook") or {}).get("strength", 0.5)
    s = 5.0 + 1.7 * math.log(tm + 0.25) + STANCE_SHIFT[p["stance"]] + (0.3 if on_target else -0.6)
    s += 1.4 * (hook - 0.5) + 0.8 * (oc["openness"] - 0.5)
    lang = (card.get("language") or "").lower()
    if "arabic" in lang and "Arabic" not in p["language"]:
        s -= 1.2
    w = (snap or {}).get("weather") or {}
    if w.get("feels_c") is not None and w["feels_c"] > 40:
        s -= 0.2
    score = float(np.clip(s + rng.normal(0, 1.2), 0, 10))
    eng, drop, att = [], None, 1.0
    for k, _seg in enumerate(card["segments"]):
        base = 0.9 if k else 0.78 + 0.2 * hook
        lg = math.log(base / (1 - base)) + 0.45 * (score - 5) / 2.5 - 0.08 * k - (0.9 if p["stance"] == "disengaged" else 0)
        e = float(np.clip(_sig(lg + rng.normal(0, 0.35)), 0.05, 0.995))
        eng.append(round(e, 3))
        att *= e
        if drop is None and att < 0.5:
            drop = k + 1
    sent = "positive" if score >= 6.5 else "negative" if score < 4.5 else "neutral"
    emo = {"positive": "joy", "neutral": "boredom" if p["stance"] == "disengaged" else "anticipation",
           "negative": "skepticism" if p["stance"] in ("skeptic", "contrarian") else "annoyance"}[sent]
    best = int(np.argmax(eng)) if eng else 0
    extra = {}
    n_opt = len(card.get("poll_options") or [])
    if n_opt:
        # vote with probability rising with interest; option preference tilted by stance so the split is not uniform
        votes = rng.random() < _sig(-0.5 + 0.5 * (score - 5) + 1.2 * (tm - 1))
        tilt = np.linspace(1.0, 0.4, n_opt) if p["stance"] in ("enthusiast", "neutral") else np.linspace(0.4, 1.0, n_opt)
        extra["poll_choice"] = int(rng.choice(n_opt, p=tilt / tilt.sum()) + 1) if votes else 0
    return extra | {"score": round(score, 1), "sentiment": sent, "primary_emotion": emo, "emotion_intensity": round(min(1, abs(score - 5) / 5 + 0.2), 2),
            "would_share": round(_sig(-3.3 + 0.6 * (score - 5) + 2.0 * (oc["extraversion"] - 0.5)), 3),
            "would_comment": round(_sig(-2.8 + 0.35 * abs(score - 5) + (0.8 if p["stance"] == "contrarian" else 0)), 3),
            "would_follow": round(_sig(-3.6 + 0.55 * (score - 5)), 3),
            "novelty": round(float(np.clip(0.5 + 0.3 * (oc["openness"] - 0.5) + rng.normal(0, 0.15), 0, 1)), 2),
            "segment_engagement": eng, "drop_segment": drop,
            "drivers": ["relatability"] if tm > 1.2 else ["curiosity gap"] if hook > 0.6 else [],
            "decision_mode": "emotional" if oc["neuroticism"] > 0.55 else "rational" if oc["conscientiousness"] > 0.6 else "habitual",
            "objection": "" if score >= 6 else ("not for me" if tm < 1 else "weak claims" if p["stance"] == "skeptic" else "too slow"),
            "quote": f"{TAG} {sent}; liked '{card['segments'][best].get('label', '') if card['segments'] else ''}'" + (f", lost me at part {drop}" if drop else ""),
            "reason": f"{TAG} topic interest x{tm:.2f}, stance {p['stance']}"}


def action(agent, feed: list[dict], platform: str, rng: np.random.Generator) -> dict:
    """Rule-based social behaviour mirroring the LLM action schema."""
    ex = agent.persona.get("ocean", {}).get("extraversion", 0.5) if agent.persona.get("ocean") else 0.6
    acts = []
    op = agent.opinion
    for f in feed[:4]:
        align = 1 - abs(op - f.get("stance", 5)) / 10
        if rng.random() < 0.35 * align:
            acts.append({"type": "LIKE" if platform == "feed" else "UPVOTE", "post_id": f["id"]})
        elif platform == "forum" and rng.random() < 0.12 * (1 - align):
            acts.append({"type": "DOWNVOTE", "post_id": f["id"]})
        if rng.random() < 0.12 * (0.5 + ex) and len(acts) < 3:
            verb = "agree" if align > 0.6 else "disagree"
            acts.append({"type": "COMMENT", "post_id": f["id"], "content": f"{TAG} {verb} ({op:.0f}/10)"})
        if platform == "feed" and op > 7 and rng.random() < 0.15 * ex and len(acts) < 3:
            acts.append({"type": "REPOST", "post_id": f["id"]})
        if len(acts) >= 3:
            break
    if agent.kind == "stakeholder" and rng.random() < 0.3:
        acts.append({"type": "POST", "content": f"{TAG} {agent.name} weighs in ({agent.persona.get('stance', 'neutral')})"})
    if feed:
        mean = float(np.mean([f.get("stance", op) for f in feed]))
        agree = agent.persona.get("ocean", {}).get("agreeableness", 0.5) if agent.persona.get("ocean") else 0.5
        if agent.persona.get("stance") == "contrarian":
            op = op + 0.2 * np.sign(op - mean)
        else:
            op = op + 0.25 * agree * (mean - op)
    return {"actions": acts[:3] or [{"type": "DO_NOTHING"}], "opinion": float(np.clip(op + rng.normal(0, 0.15), 0, 10)),
            "thought": f"{TAG} scrolling"}


def stakeholders(entities: list[dict], regions: list[str], k: int) -> list[dict]:
    acting = [e for e in entities if e.get("type") in ("Brand", "Organization", "Person", "MediaOutlet", "Community")]
    if len(acting) < k:
        acting += [e for e in entities if e not in acting and e.get("type") not in ("Place", "Event", "Claim")
                   and e["label"][:1].isupper() and not e["key"].startswith("topic:")][: k - len(acting)]
    out = []
    for e in acting[:k]:
        role = {"Brand": "brand", "Organization": "organisation", "Person": "public_figure", "MediaOutlet": "media"}.get(e["type"], "community")
        out.append({"entity": e["label"], "name": e["label"], "handle": "".join(ch for ch in e["label"].lower() if ch.isalnum())[:15] or "account",
                    "role": role, "region": regions[0] if regions else "*", "stance": "neutral",
                    "persona": f"{TAG} {e['label']} ({e['type']}): {e.get('summary', '')}", "activity": 0.4})
    return out


def config(hours: int) -> dict:
    return {"hot_topics": [], "narrative": f"{TAG} default configuration; no model was used.", "scheduled_events": [],
            "feed": {"recency_weight": 0.35, "popularity_weight": 0.35, "relevance_weight": 0.3, "echo_chamber": 0.55},
            "forum": {"recency_weight": 0.3, "popularity_weight": 0.4, "relevance_weight": 0.3, "echo_chamber": 0.45},
            "analysis_focus": "How different audiences react and why."}
