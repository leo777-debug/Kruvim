"""Explicit synthetic seeds and bounded raking of approved native UAE marginals.

No constants here are measured demographic shares. Uniform support and legacy agent
values are placeholder seeds only; demographic facts enter exclusively as observations.
"""
from __future__ import annotations

import hashlib
import math
from collections import defaultdict

import numpy as np

EMIRATES = {"AE-DXB": "Dubai", "AE-AUH": "Abu Dhabi", "AE-SHJ": "Sharjah", "AE-NE": "Northern emirates"}
NATIONALITIES = ["Emirati", "Indian: Kerala/South", "Indian: Hindi-belt/North", "Indian: Other", "Pakistani",
                 "Bangladeshi", "Filipino", "Egyptian", "Other Arab", "Western", "Other Asian", "Other"]
INCOME_BANDS = ["labour / shared accommodation", "mid-skill", "professional", "executive", "business owner"]
HOUSEHOLDS = ["single worker away from family", "family", "Emirati multigenerational"]
LANGUAGES = ["Arabic", "English", "Hindi/Urdu", "Malayalam", "Tagalog", "Bengali", "Other"]
CALENDARS = ["Ramadan/Eid", "Diwali", "Onam", "Christmas", "Other"]
VISA_TYPES = ["citizen", "employment", "dependent", "business", "visitor"]
VISITOR_ORIGINS = ["GCC", "India", "UK", "Russia", "China", "Other"]
DOMAINS = {"residence_emirate": list(EMIRATES), "work_emirate": list(EMIRATES), "nationality_group": NATIONALITIES,
           "income_band": INCOME_BANDS, "household_type": HOUSEHOLDS, "language": LANGUAGES,
           "calendar_membership": CALENDARS, "visa_type": VISA_TYPES, "status": ["resident", "visitor"],
           "visitor_source_country": VISITOR_ORIGINS, "sex": ["female", "male"],
           "age_band": ["16–24", "25–34", "35–44", "45–54", "55–70"]}
PLACEHOLDER_ID = hashlib.sha256(b"placeholder_priors").hexdigest()[:32]
LABEL = "estimate, source pending"


def placeholder_provenance():
    return {"status": "placeholder", "label": LABEL, "source_ids": [PLACEHOLDER_ID], "observation_ids": [],
            "sources": [{"name": "Synthetic placeholder configuration", "url": "https://github.com/leo777-debug/Kruvim/tree/kruvim/backend/app/services/population", "status": "placeholder"}],
            "attribute_confidence": {k: {"status": "placeholder", "label": LABEL, "confidence": 0,
                "source_ids": [PLACEHOLDER_ID], "observation_ids": []} for k in [*DOMAINS, "remittance_share", "platform_habits", "salary_cycle"]},
            "conflicts": [], "coverage_gaps": [{"attribute": k, "reason": "No approved native observations loaded"} for k in DOMAINS]}


def seed(pop):
    """Enrich stable row IDs without changing old country/age/sex arrays or requiring a new cache."""
    rng = np.random.default_rng(pop.seed ^ 0x554145)
    n = pop.n
    ae = pop.region == 0
    extra = {key: rng.integers(len(values), size=n, dtype=np.int8) for key, values in DOMAINS.items()
             if key not in ("sex", "age_band")}
    # These are explicitly labelled structural rules, not nationality/income distributions.
    extra["nationality_group"][ae & pop.citizen] = 0
    expats = ae & ~pop.citizen
    extra["nationality_group"][expats] = rng.integers(1, len(NATIONALITIES), int(expats.sum()), dtype=np.int8)
    extra["status"][:] = 0  # Residents by default. Visitor layer is opt-in and separately estimated.
    extra["visa_type"][ae & pop.citizen] = 0
    extra["visa_type"][expats] = rng.integers(1, 4, int(expats.sum()), dtype=np.int8)
    extra["household_type"][expats] %= 2
    extra["income_band"] = pop.income.astype(np.int8).copy()
    # Language/calendar support is a declared persona rule, never an adoption or nationality share.
    language_support = [[0, 1], [1, 2, 3, 6], [1, 2, 6], [1, 2, 6], [1, 2], [1, 5], [1, 4],
                        [0, 1], [0, 1], [1, 6], [1, 6], list(range(len(LANGUAGES)))]
    calendar_support = [[0], [1, 2, 3, 4], [0, 1, 3, 4], [0, 1, 3, 4], [0, 3, 4], [0, 3, 4],
                        [0, 3, 4], [0, 3, 4], [0, 3, 4], [3, 4], list(range(len(CALENDARS))), list(range(len(CALENDARS)))]
    for group in range(len(NATIONALITIES)):
        members = np.flatnonzero(ae & (extra["nationality_group"] == group))
        extra["language"][members] = rng.choice(language_support[group], len(members))
        extra["calendar_membership"][members] = rng.choice(calendar_support[group], len(members))
    # Every group has full non-zero seed support so imported cross-tabs can change it.
    extra["remittance_share"] = np.full(n, np.nan, dtype=np.float32)
    extra["salary_day"] = np.zeros(n, dtype=np.int8)  # Unknown, not an invented payday.
    extra["whatsapp"] = np.zeros(n, dtype=bool)  # No unloaded adoption statistic claimed.
    pop.uae = extra
    return pop


def columns(pop, idx):
    return {**{k: v[idx] for k, v in pop.uae.items()}, "sex": pop.male[idx].astype(np.int8), "age_band": pop.age_band[idx]}


def rake(columns, targets, max_iterations=200, tolerance=1e-6):
    """IPF binary cell constraints, including conditional geography; no missing cells are synthesized.

    Each target has mask, optional scope mask, and an explicitly supplied fraction.
    Returns weights plus residuals; impossible constraints are reported to callers.
    """
    n = len(next(iter(columns.values())))
    weights = np.ones(n, dtype=np.float64)
    resolved = []
    for target in targets:
        scope = np.asarray(target.get("scope", np.ones(n, dtype=bool)), dtype=bool)
        cell = np.asarray(target["mask"], dtype=bool) & scope
        desired = float(target["fraction"])
        if not 0 <= desired <= 1 or not scope.any() or (desired > 0 and not cell.any()) or (desired < 1 and not (scope & ~cell).any()):
            raise ValueError("Marginal cannot be fitted: absent seed support or invalid target")
        resolved.append((scope, cell, desired))
    error = 0.
    for _ in range(max_iterations):
        for scope, cell, desired in resolved:
            total = weights[scope].sum()
            current = weights[cell].sum()
            other = scope & ~cell
            if current > 0:
                weights[cell] *= desired * total / current
            if total - current > 0:
                weights[other] *= (1 - desired) * total / (total - current)
        weights *= n / max(weights.sum(), 1e-300)
        error = max((abs(weights[cell].sum() / max(weights[scope].sum(), 1e-300) - desired)
                     for scope, cell, desired in resolved), default=0.)
        if error <= tolerance:
            break
    return weights, error


def reconcile(observations, sources, now, tolerance=.03):
    """Pick the best-supported conflicting cell; retain every competing value and widen uncertainty.

    Only explicit population_share fractions/percents are fitted. Counts, proxies and
    unsupported cells remain native observations and coverage gaps until a denominator/mapping exists.
    """
    from app.services.sources import eligible
    groups = defaultdict(list)
    provenance = placeholder_provenance()
    totals = {(o.source_id, o.geography, o.period_end): o for o in observations
              if o.metric == "population_total" and o.unit in ("persons", "count") and o.value > 0 and not o.dimensions}
    denominators = {}
    for o in observations:
        source = sources.get(o.source_id)
        if not source or not eligible(source) or not o.geography.startswith("AE"):
            continue
        if o.metric == "population_total":
            continue
        denominator = totals.get((o.source_id, o.geography, o.period_end))
        is_count = o.metric == "population_count" and o.unit in ("persons", "count") and denominator is not None
        if not is_count and (o.metric != "population_share" or o.unit not in ("percent", "fraction")):
            provenance["coverage_gaps"].append({"attribute": o.metric, "observation_id": o.id,
                "reason": "Native figure retained; no explicit population-share denominator/mapping"})
            continue
        mapping = source.config.get("population_dimension_map", {}) if hasattr(source, "config") else {}
        dimensions = {}
        for native_key, native_value in o.dimensions.items():
            rule = mapping.get(native_key, {})
            dimensions[rule.get("dimension", native_key)] = rule.get("values", {}).get(str(native_value), native_value)
        if not dimensions or any(k not in DOMAINS or v not in DOMAINS[k] for k, v in dimensions.items()):
            provenance["coverage_gaps"].append({"attribute": o.metric, "observation_id": o.id,
                "reason": "Unmapped publisher dimension code; explicit mapping required"})
            continue
        if o.geography != "AE" and o.geography not in EMIRATES:
            continue
        value = o.value / (denominator.value if is_count else 100 if o.unit == "percent" else 1)
        if is_count:
            denominators[o.id] = denominator.id
        if not 0 <= value <= 1:
            provenance["coverage_gaps"].append({"attribute": o.metric, "observation_id": o.id, "reason": "Invalid share"})
            continue
        age = max(0, (now - o.period_end).total_seconds() / 86400)
        quality = source.reliability * math.exp(-age / (365 * 5))
        quality *= 1 if (source.geography_level == "emirate") == (o.geography != "AE") else .7
        groups[(o.geography, tuple(sorted(dimensions.items())))].append((o, value, quality))
    targets, covered = [], set()
    for (geography, dimension_items), candidates in sorted(groups.items()):
        # Retain latest period per source; old periods remain in the registry, never interpolated.
        latest = {}
        for candidate in candidates:
            if candidate[0].source_id not in latest or candidate[0].period_end > latest[candidate[0].source_id][0].period_end:
                latest[candidate[0].source_id] = candidate
        candidates = sorted(latest.values(), key=lambda x: (-x[2], x[0].source_id, x[0].id))
        winner, value, quality = candidates[0]
        spread = max(x[1] for x in candidates) - min(x[1] for x in candidates)
        conflict = spread > tolerance
        ids = [x[0].id for x in candidates]
        ids += [denominators[x[0].id] for x in candidates if x[0].id in denominators]
        source_ids = [x[0].source_id for x in candidates]
        if conflict:
            provenance["conflicts"].append({"geography": geography, "dimensions": dict(dimension_items),
                "values": [{"observation_id": o.id, "source_id": o.source_id, "fraction": v,
                            "period_end": o.period_end.isoformat()} for o, v, _ in candidates],
                "selected_observation_id": winner.id, "reason": "Highest reliability/recency/geography score; disagreement not averaged",
                "uncertainty_widening": spread})
        confidence = min(1., quality + (.1 * (len(candidates) - 1) if not conflict else 0)) * (1 - spread if conflict else 1)
        for attribute, _ in dimension_items:
            covered.add(attribute)
            prior = provenance["attribute_confidence"].get(attribute, {})
            provenance["attribute_confidence"][attribute] = {"status": "partial", "label": "Partially sourced; missing cells remain estimates",
                "confidence": min(prior.get("confidence", confidence) or confidence, confidence),
                "source_ids": sorted(set(prior.get("source_ids", []) + source_ids)),
                "observation_ids": sorted(set(prior.get("observation_ids", []) + ids)), "conflict": conflict or prior.get("conflict", False)}
        provenance["source_ids"] += source_ids
        provenance["observation_ids"] += ids
        targets.append({"geography": geography, "dimensions": dict(dimension_items), "fraction": value,
                        "observation_id": winner.id})
    # Coverage is not declared complete merely because one cell exists.
    for attribute in covered:
        provenance["coverage_gaps"].append({"attribute": attribute, "reason": "Only mapped cells fitted; unobserved cells retain placeholder support"})
    provenance["source_ids"] = sorted(set(provenance["source_ids"]))
    provenance["observation_ids"] = sorted(set(provenance["observation_ids"]))
    provenance["sources"] += [{"name": sources[k].name, "publisher": sources[k].publisher, "url": sources[k].url,
        "status": sources[k].status, "attribution": sources[k].attribution} for k in provenance["source_ids"] if k in sources and k != PLACEHOLDER_ID]
    if targets:
        provenance["status"], provenance["label"] = "partial", "Partially sourced population; " + LABEL
    return targets, provenance


def notice(provenance):
    p = provenance or placeholder_provenance()
    text = "Audience population: " + p.get("label", LABEL) + ". These are synthetic agents, not measured followers."
    placeholders = [k for k, v in p.get("attribute_confidence", {}).items() if v.get("status") in ("placeholder", "partial")]
    text += "\n\nAttributes with placeholder support: " + ", ".join(k.replace("_", " ") for k in placeholders) + "."
    text += "\n\nSources: " + "; ".join(f"{x['name']} ({x['url']})" for x in p.get("sources", [])) + "."
    if p.get("conflicts"):
        text += "\n\nConflicts: " + "; ".join(f"{x['geography']}: {', '.join(x['dimensions'])}; competing native figures retained, uncertainty widened" for x in p["conflicts"]) + "."
    text += "\n\nCoverage gaps: " + "; ".join(dict.fromkeys(f"{x['attribute'].replace('_', ' ')} — {x['reason']}" for x in p.get("coverage_gaps", []))) + "."
    return text


def fit(pop, targets):
    idx = np.flatnonzero(pop.region == 0)
    if not idx.size or not targets:
        return pop
    data = columns(pop, idx)
    constraints = []
    for target in targets:
        scope = np.ones(idx.size, bool) if target["geography"] == "AE" else data["residence_emirate"] == list(EMIRATES).index(target["geography"])
        mask = np.ones(idx.size, bool)
        for key, value in target["dimensions"].items():
            mask &= data[key] == DOMAINS[key].index(value)
        constraints.append({"scope": scope, "mask": mask, "fraction": target["fraction"]})
    try:
        weights, residual = rake(data, constraints)
    except ValueError as exc:
        pop.provenance["coverage_gaps"].append({"attribute": "reconciliation", "reason": str(exc)})
        return pop
    if residual > .01:
        pop.provenance["coverage_gaps"].append({"attribute": "reconciliation", "reason": "Joint constraints did not converge",
                                                "residual": float(residual)})
        return pop  # Keep explicit placeholder seed instead of pretending an invalid fit is sourced.
    rng = np.random.default_rng(pop.seed ^ 0x52414B45)
    points = (np.arange(idx.size) + rng.random()) / idx.size
    selected = idx[np.minimum(np.searchsorted(np.cumsum(weights) / weights.sum(), points), idx.size - 1)]
    for key in pop.uae:
        pop.uae[key][idx] = pop.uae[key][selected].copy()
    for key in ("age", "age_band", "male", "citizen", "origin", "education", "income", "profession", "lang", "platforms", "attitudes"):
        getattr(pop, key)[idx] = getattr(pop, key)[selected].copy()
    pop.citizen[idx] = pop.uae["nationality_group"][idx] == 0
    pop.provenance["raking_residual"] = float(residual)
    return pop


def persona(pop, i):
    if pop.region[i] != 0:
        return {}
    result = {key: domain[int(pop.uae[key][i])] for key, domain in DOMAINS.items() if key in pop.uae}
    share = float(pop.uae["remittance_share"][i])
    result.update(remittance_share=share if math.isfinite(share) else None, salary_day=None,
                  languages=[result["language"], "English"] if result["language"] != "English" else ["English"],
                  media_languages=[result["language"]], calendar_memberships=[result["calendar_membership"]],
                  occupation_band=result["income_band"],
                  population_provenance=pop.provenance, population_status=pop.provenance["status"], population_label=pop.provenance["label"],
                  city=EMIRATES[result["residence_emirate"]], origin=result["nationality_group"])
    return result
