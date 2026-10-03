"""Creator-specific sampling and evidence grounded in prepared snapshots, without extra model calls."""
import re

import numpy as np

from app.services.population.regions import REGIONS

PRESETS = [
    {"id": "gen-z-gulf", "name": "Gen Z Gulf", "description": "Young adults in Saudi Arabia and the UAE.", "filters": {"regions": ["SA", "AE"], "age_min": 18, "age_max": 24}},
    {"id": "gen-z-saudi", "name": "Gen Z Saudi", "description": "Saudi residents aged 18–24.", "filters": {"regions": ["SA"], "age_min": 18, "age_max": 24}},
    {"id": "gen-z-uae", "name": "Gen Z UAE", "description": "UAE residents aged 18–24.", "filters": {"regions": ["AE"], "age_min": 18, "age_max": 24}},
    {"id": "saudi-gamers", "name": "Gen Z Saudi gamers", "description": "Young adults in Saudi Arabia interested in gaming.", "filters": {"regions": ["SA"], "age_min": 18, "age_max": 24, "interests": ["gaming"]}},
    {"id": "ksa-women", "name": "Young women in KSA", "description": "Women aged 18–34 in Saudi Arabia.", "filters": {"regions": ["SA"], "age_min": 18, "age_max": 34, "genders": ["female"]}},
    {"id": "gulf-students", "name": "Gulf students", "description": "Students in Saudi Arabia and the UAE.", "filters": {"regions": ["SA", "AE"], "age_min": 18, "age_max": 29, "professions": ["student"]}},
]


def audience_weights(pop, indices, split):
    """Iterative proportional fitting of supplied marginals on available synthetic people.

    Unknown genders, unsupported countries and ages outside 16–70 are disclosed, not fabricated.
    Returns normalized weights and coverage diagnostics. No assumption of a known joint distribution.
    """
    idx = np.asarray(indices)
    w = np.ones(idx.size, dtype=float)
    groups, coverage, clipped = [], {}, []
    if not idx.size:
        return w, {"coverage": {}, "warning": "No synthetic audience matches these filters."}
    for dimension in ("countries", "ages", "genders"):
        values = split.get(dimension) or {}
        if not values:
            continue
        cells = []
        supported = 0
        for label, pct in values.items():
            if dimension == "countries":
                codes = [r["code"] for r in REGIONS]
                mask = pop.region[idx] == codes.index(label) if label in codes else np.zeros(idx.size, bool)
            elif dimension == "genders":
                mask = pop.male[idx] == (label == "male") if label in ("male", "female") else np.zeros(idx.size, bool)
            else:
                lo = int(label.split('-')[0].rstrip('+'))
                hi = int(label.split('-')[1]) if '-' in label else 120
                if lo < 16 or hi > 70:
                    clipped.append(label)
                mask = (pop.age[idx] >= lo) & (pop.age[idx] <= hi)
            if mask.any():
                cells.append((mask, float(pct)))
                supported += float(pct)
        coverage[dimension] = round(supported, 2)
        if supported <= 0:
            raise ValueError(f"No supported {dimension} remain in the chosen audience. Widen your filters.")
        # Exclude unspecified/zero-share categories in each supplied marginal.
        allowed = np.zeros(idx.size, bool)
        for mask, pct in cells:
            if pct > 0:
                allowed |= mask
        w[~allowed] = 0
        groups.append([(mask, pct / supported) for mask, pct in cells])
    if not w.sum():
        raise ValueError("The follower breakdown has no supported joint audience. Widen your filters.")
    w /= w.sum()
    for _ in range(50):
        for cells in groups:
            for mask, target in cells:
                current = w[mask].sum()
                if current > 0:
                    w[mask] *= target / current
            w /= w.sum()
    errors = [abs(w[mask].sum() - target) for cells in groups for mask, target in cells]
    return w, {"coverage": coverage, "max_marginal_error_percent": round(100 * max(errors, default=0), 2),
               "method": "Raked country, age and gender marginals over available synthetic people; other traits remain synthetic priors.",
               "clipped_age_bands": clipped,
               "warning": "Unsupported demographics are excluded, ages clipped to 16–70 and supported shares normalized." if clipped or any(v < 99 for v in coverage.values()) else None}


def weighted_sample(pop, mask, n, rng, split=None, exclude=None):
    indices = np.flatnonzero(mask)
    if exclude is not None:
        indices = np.setdiff1d(indices, exclude)
    weights, diagnostics = audience_weights(pop, indices, split or {})
    count = min(n, int((weights > 0).sum()))
    return rng.choice(indices, count, replace=False, p=weights), diagnostics


def personal_signals(persona, card, snapshots):
    from app.services.datapool.retrieval import rank
    snap = snapshots.get(persona["region"], {})
    interests = " ".join(x.get("label", "") for x in persona.get("interests", []))
    query = interests + " " + str(card.get("title", "")) + " " + " ".join(card.get("keywords") or []) + " " + " ".join(persona.get("platforms", []))
    signals = snap.get("signals", [])
    return rank(signals, query, snap.get("source_weights"))


def short_video_metrics(reaction):
    # Formula defaults keep dry-run and old model schemas working.
    score = float(reaction.get("score", 5)) / 10
    share = float(reaction.get("would_share", 0))
    for key, value in {"rewatch_probability": score * 0.35, "stitch_duet_likelihood": share * 0.12,
                       "sound_reuse_likelihood": share * 0.08}.items():
        try:
            reaction[key] = round(float(np.clip(float(reaction.get(key, value)), 0, 1)), 3)
        except (ValueError, TypeError):
            reaction[key] = round(value, 3)
    reaction["comment_bait"] = str(reaction.get("comment_bait", "part 2 request" if score > .7 else "none"))[:100]
    return reaction


def creator_checks(e, voices):
    vr = [a.reaction for a in voices]
    short = e.card.get("format_key") == "short_video"
    result = {"audience_twin": e.cfg.get("audience_twin"), "stale_sources": [note for snap in e.snaps.values() for note in snap.get("stale_sources", [])],
              "retrieval_usage": e.cfg.get("retrieval_usage", {}),
              "agent_signals": {a.ref: a.cfg.get("personal_signals", []) for a in voices}}
    if short and e.platform_key in ("tiktok", "instagram", "youtube"):
        result["short_video"] = {key: round(float(np.mean([r.get(key, 0) for r in vr])), 3) for key in (
            "rewatch_probability", "stitch_duet_likelihood", "sound_reuse_likelihood")}
        result["short_video"]["comment_bait"] = [{"agent": a.ref, "response": a.reaction.get("comment_bait", "none")} for a in voices][:20]
    objections = [{"agent": a.ref, "quote": a.reaction.get("quote", ""), "evidence": a.reaction.get("objection", "")} for a in voices
                  if re.search(r"slang|dialect|language|dated|cringe", a.reaction.get("objection", ""), re.I)]
    result["language_fit"] = {"flags": objections, "note": "Agent objections are simulated evidence, not real follower comments."}
    return result
