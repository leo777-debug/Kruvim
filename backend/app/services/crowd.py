"""Free-text crowd builder: turns "who should see this" in the creator's own words into population filters plus a
crowd brief. Filters keep the audience grounded in the 1M population (counts, weighting, regions); the brief carries
everything a filter cannot express (a subculture, a belief, a mood) into every voice agent's persona."""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app.schemas.simulation import AudienceIn, CrowdSegment, CrowdTraits
from app.services.llm import BaseLLM, Usage
from app.services.population.regions import (
    INCOME_LABELS,
    INTEREST_LABELS,
    PLATFORM_LABELS,
    PROFESSIONS,
    REGIONS,
    STANCES,
)
from app.services.population.uae import DOMAINS, EMIRATES

# Fields the crowd builder owns. Anything else on the audience (creator split, "match my audience") is left alone.
FIELDS = ("regions", "age_min", "age_max", "genders", "platforms", "citizens_only", "expats_only", "interests", "professions",
          "incomes", "stances", "education_min", "emirates", "nationality_groups", "income_bands", "languages", "ocean")
LISTS = {"regions": [r["code"] for r in REGIONS] + list(EMIRATES), "genders": ["female", "male"], "platforms": list(PLATFORM_LABELS),
         "interests": list(INTEREST_LABELS), "professions": PROFESSIONS, "incomes": INCOME_LABELS, "stances": STANCES,
         "emirates": list(EMIRATES), "nationality_groups": DOMAINS["nationality_group"], "income_bands": DOMAINS["income_band"],
         "languages": DOMAINS["language"]}
OCEAN = ("openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism")
BRIEF_MAX = 2000

SYSTEM = """You build the audience for Kruvim, a tool that tests social content on a synthetic population of one million
people. The creator describes the crowd they want in their own words, over one or more messages. Translate what they say
into population filters where a filter fits, and keep everything else in a short crowd brief that every simulated person
will read as part of who they are.

Rules:
- Use only the allowed values below. Map loosely ("Gen Z" -> age 16-27, "Gulf" -> AE + SA, "gamers" -> interests
  gaming, "moms" -> genders female + interests family). Never invent values; a place with no region stays in the brief.
- Each message refines the current audience. Keep current filters unless the creator changes or removes them.
- Filters narrow the population; do not over-filter. Ages must stay within 16-70. Leave a list empty for "anyone".
- The brief is 1-4 plain sentences in third person describing the crowd as people ("They follow street-food creators,
  are sceptical of influencer ads..."). Merge the new message into the previous brief; drop anything the creator retracts.
  Do not restate filters already captured (ages, regions) unless needed for nuance. Empty if nothing goes beyond filters.
- traits: how this crowd behaves online, for the thousands of statistical crowd agents that never read the brief.
  activity and sharing are multipliers (1 = typical; 2 = doomscrolls / forwards everything; 0.5 = lurks / rarely
  shares); contrarian = share who push back against the room (typical 0.1); forum = share who argue in threads rather
  than the feed (typical 0.2). Use null for anything the creator did not imply. Keep current traits unless changed.
- segments: 2-4 named groups inside the crowd that the results should compare. If the creator names groups ("the
  skeptics vs the fans", "students against working parents"), use exactly those. Otherwise keep the current segments,
  or propose 2-3 contrasts that matter for this crowd. Define each with filters (usually stances, ages, genders,
  interests, professions, incomes) that pick that group out of the crowd; do not repeat the crowd's own filters.
- reply: one or two friendly sentences telling the creator what you set and anything you could not map.

Allowed values:
{vocab}

Reply with JSON only:
{{"filters": {{"regions": [...], "age_min": <int or null>, "age_max": <int or null>, "genders": [...], "platforms": [...],
  "interests": [...], "professions": [...], "incomes": [...], "stances": [...], "citizens_only": <bool>, "expats_only": <bool>,
  "education_min": <0-3 or null>, "emirates": [...], "nationality_groups": [...], "income_bands": [...], "languages": [...],
  "ocean": {{"<trait>": [<lo 0-1>, <hi 0-1>]}}}},
 "traits": {{"activity": <0.3-3 or null>, "sharing": <0.3-3 or null>, "contrarian": <0-1 or null>, "forum": <0-1 or null>}},
 "segments": [{{"name": "<short name>", "description": "<one line>", "filters": {{<same keys as filters, only what defines the group>}}}}],
 "brief": "<crowd brief>", "reply": "<what you did>"}}"""


def vocab() -> str:
    return json.dumps({
        "regions": {r["code"]: r["name"] for r in REGIONS} | {k: f"{v} (UAE emirate)" for k, v in EMIRATES.items()},
        "genders": LISTS["genders"], "platforms": LISTS["platforms"], "interests": INTEREST_LABELS, "professions": PROFESSIONS,
        "incomes": INCOME_LABELS, "stances": STANCES, "education_min": {"0": "secondary or less", "1": "diploma", "2": "bachelor's",
                                                                      "3": "postgraduate"},
        "uae_only": {"nationality_groups": LISTS["nationality_groups"], "income_bands": LISTS["income_bands"],
                     "languages": LISTS["languages"]},
        "ocean_traits": OCEAN}, ensure_ascii=False)


def _num(v, lo: float, hi: float, cast=int):
    try:
        return max(lo, min(hi, cast(v)))
    except (TypeError, ValueError):
        return None


def coerce(filters: dict) -> dict:
    """Only the filter keys given, with unknown values dropped and numbers clamped."""
    out = {}
    for k in FIELDS:
        if k not in filters:
            continue
        v = filters[k]
        if k in LISTS:
            allowed = LISTS[k]
            out[k] = list(dict.fromkeys(x for x in (v or []) if isinstance(x, str) and x in allowed))
        elif k in ("age_min", "age_max"):
            out[k] = _num(v, 16, 70)
        elif k == "education_min":
            out[k] = _num(v, 0, 3)
        elif k in ("citizens_only", "expats_only"):
            out[k] = bool(v)
        elif k == "ocean" and isinstance(v, dict):
            rng = {t: (_num(r[0], 0.0, 1.0, float), _num(r[1], 0.0, 1.0, float)) for t, r in v.items()
                   if t in OCEAN and isinstance(r, (list, tuple)) and len(r) == 2}
            out[k] = {t: sorted(r) for t, r in rng.items() if None not in r and r != (0.0, 1.0)}
    return out


def sanitize(current: dict, filters: dict) -> dict:
    """Merge proposed filters onto the current audience, dropping unknown values and any field that fails validation."""
    out = dict(current) | coerce(filters)
    if not out.get("regions"):
        out["regions"] = current.get("regions") or []         # a crowd always lives somewhere; keep the last places
    if out.get("age_min") and out.get("age_max") and out["age_min"] > out["age_max"]:
        out["age_min"], out["age_max"] = out["age_max"], out["age_min"]
    if out.get("citizens_only") and out.get("expats_only"):
        out["expats_only"] = False
    try:
        return AudienceIn.model_validate(out).model_dump()
    except ValidationError as exc:
        bad = {str(e["loc"][0]) for e in exc.errors() if e.get("loc")}
        return AudienceIn.model_validate({k: v for k, v in out.items() if k not in bad} | {k: current[k] for k in bad if k in current}).model_dump()


def traits(current: dict, proposed) -> dict:
    """Merge proposed behaviour traits onto the current ones; out-of-range values are clamped, junk is ignored."""
    out = dict(current.get("traits") or {})
    bounds = {"activity": (0.3, 3.0), "sharing": (0.3, 3.0), "contrarian": (0.0, 1.0), "forum": (0.0, 1.0)}
    for k, (lo, hi) in bounds.items():
        if isinstance(proposed, dict) and k in proposed:
            out[k] = None if proposed[k] is None else _num(proposed[k], lo, hi, float)
    return CrowdTraits.model_validate(out).model_dump()


def segments(proposed, fallback: list) -> list[dict]:
    """Keep only well-formed, distinct segments; an unusable proposal keeps the previous segments."""
    out = []
    for seg in proposed if isinstance(proposed, list) else []:
        try:
            s = CrowdSegment.model_validate({"name": str(seg.get("name", "")).strip()[:80], "description": str(seg.get("description") or "")[:300],
                                             "filters": coerce(seg.get("filters") or {})})
        except (ValidationError, AttributeError, TypeError):
            continue
        if s.filters and s.name.lower() not in {x["name"].lower() for x in out}:
            out.append(s.model_dump())
    return out[:4] if len(out) >= 2 else list(fallback or [])


async def interpret(message: str, current: dict, llm: BaseLLM, usage: Usage) -> dict:
    """One chat turn. Returns {"audience": updated audience, "reply": text, "mode": "model" | "keywords"}."""
    if llm.is_dry:
        return keywords(message, current)
    user = json.dumps({"current_filters": {k: current.get(k) for k in FIELDS}, "current_brief": current.get("brief", ""),
                       "current_traits": current.get("traits") or {}, "current_segments": current.get("segments") or [],
                       "message": message}, ensure_ascii=False)
    out = await llm.complete_json(system=SYSTEM.format(vocab=vocab()), user=user, role="brief", max_tokens=1800, usage=usage,
                                  temperature=0.2)
    aud = sanitize(current, out.get("filters") or {})
    aud["brief"] = str(out.get("brief") or "").strip()[:BRIEF_MAX]
    aud["traits"] = traits(current, out.get("traits"))
    aud["segments"] = segments(out.get("segments"), current.get("segments"))
    return {"audience": aud, "reply": str(out.get("reply") or "Updated the crowd.").strip()[:600], "mode": "model"}


# ---- keyword fallback (dry run, or when the model is unavailable) ---------------------------------------------------
GULF = ["AE", "SA", "KW", "QA", "BH", "OM"]
DEMONYMS = {"SA": r"\bsaudis?\b", "AE": r"\bemirat", "US": r"\bamerican", "GB": r"\bbritish|\bbrits?\b|\bengland|\benglish people",
            "MA": r"\bmorocc", "IN": r"\bindians? in india|\bdesi\b"}
AGE_WORDS = {"gen z": (16, 27), "genz": (16, 27), "zoomer": (16, 27), "teen": (16, 19), "student": (16, 25), "millennial": (28, 43),
             "gen x": (44, 59), "boomer": (60, 70), "young": (16, 30), "older": (45, 70), "retire": (60, 70)}
GENDER_WORDS = {"female": ["women", "woman", "female", "girls", "moms", "mothers", "ladies"],
                "male": ["men", "man", "male", "guys", "boys", "dads", "fathers"]}
INTEREST_WORDS = {"gaming": ["gamer", "gaming", "esports"], "fitness_health": ["fitness", "gym", "workout", "health"],
                  "fashion_beauty": ["fashion", "beauty", "makeup", "skincare"], "finance": ["finance", "crypto", "investing", "money"],
                  "news_politics": ["news", "politic"], "religion": ["religio", "faith", "islam", "church"],
                  "family": ["parent", "moms", "dads", "family"], "film_tv": ["film", "movie", "tv", "series", "anime"],
                  "tech": ["tech", "developer", "coder", "gadget", "ai "], "food": ["food", "cook", "recipe", "restaurant"],
                  "cars": ["car ", "cars", "motor"], "travel": ["travel"], "sports": ["sport", "football", "soccer", "cricket"],
                  "music": ["music", "concert"], "comedy": ["comedy", "meme", "funny"], "education": ["learn", "educat"]}


TRAIT_WORDS = [("activity", r"doomscroll|always online|scroll all day|chronically online|addicted", 1.8),
               ("activity", r"\blurk|rarely (?:post|open|use)|barely (?:use|online)|offline", 0.5),
               ("sharing", r"share everything|forward(?:s|ing)? everything|reshar|repost a lot", 1.8),
               ("contrarian", r"skeptic|sceptic|cynic|roll(?:s)? their eyes|argue|troll|hater", 0.35),
               ("forum", r"reddit|forum|threads|argue in the comments|comment section", 0.45)]
SEGMENT_WORDS = {"Fans": (r"\bfans?\b|enthusias|\blove\b|superfans?", "Enthusiasts who are primed to like it", ["enthusiast"]),
                 "Skeptics": (r"skeptic|sceptic|cynic|roll(?:s)? their eyes", "People who want proof before they buy in", ["skeptic"]),
                 "Contrarians": (r"contrarian|hater|troll|argue", "People who look for what is wrong", ["contrarian"]),
                 "Casual scrollers": (r"casual|lurk|disengaged|barely", "People who barely pay attention", ["disengaged", "neutral"])}


def keywords(message: str, current: dict) -> dict:
    t = f" {message.lower()} "
    f: dict = {}
    said: list[str] = []
    if m := re.search(r"\b(1[6-9]|[2-6]\d|70)\s*(?:-|–|to)\s*(1[6-9]|[2-6]\d|70)\b", t):
        f["age_min"], f["age_max"] = sorted((int(m[1]), int(m[2])))
    elif m := re.search(r"\b(?:over|above|older than)\s+(1[6-9]|[2-6]\d)\b", t):
        f["age_min"], f["age_max"] = int(m[1]), 70
    elif m := re.search(r"\b(?:under|below|younger than)\s+(1[7-9]|[2-6]\d|70)\b", t):
        f["age_min"], f["age_max"] = 16, int(m[1])
    else:
        for w, (lo, hi) in AGE_WORDS.items():
            if w in t:
                f["age_min"], f["age_max"] = lo, hi
                break
    if "age_min" in f:
        said.append(f"ages {f['age_min']}–{f['age_max']}")
    genders = [g for g, ws in GENDER_WORDS.items() if any(re.search(rf"\b{w}\b", t) for w in ws)]
    if len(genders) == 1:
        f["genders"] = genders
        said.append("women" if genders[0] == "female" else "men")
    emirates = [c for c, n in EMIRATES.items() if re.search(rf"\b{n.lower()}\b", t)]
    names = lambda r: {r["name"], r["short"]} | ({r["city"]} if r["city"] not in EMIRATES.values() else set())  # noqa: E731
    # "egypt" also matches "egyptian"; short names ("uk", "usa") must match whole words
    word = lambda n: rf"\b{re.escape(n.lower())}" + (r"\b" if len(n) <= 3 else "")  # noqa: E731
    regs = [r["code"] for r in REGIONS if any(re.search(word(n), t) for n in names(r))
            or re.search(rf"(?:{DEMONYMS.get(r['code'], '$^')})(?!\w*\s+expat)", t)] + emirates  # "British expats" is a nationality
    if re.search(r"\bgulf\b|\bgcc\b|\bkhaleeji\b", t):
        regs += [c for c in GULF if c in LISTS["regions"] and c not in regs]
    if regs and re.search(r"\b(too|also|add|plus|as well)\b", t):
        regs = list(dict.fromkeys((current.get("regions") or []) + regs))
    if regs:
        f["regions"] = regs
        said.append(", ".join({r["code"]: r["short"] for r in REGIONS}.get(c) or EMIRATES[c] for c in regs))
    ints = [k for k, ws in INTEREST_WORDS.items() if any(re.search(rf"\b{w}", t) for w in ws)]
    if ints:
        f["interests"] = list(dict.fromkeys((current.get("interests") or []) + ints))
        said.append("into " + ", ".join(INTEREST_LABELS[k].lower() for k in ints))
    plats = [k for k, label in PLATFORM_LABELS.items() if k != "x" and label.lower() in t]
    if plats:
        f["platforms"] = plats
        said.append("on " + ", ".join(PLATFORM_LABELS[k] for k in plats))
    profs = [p for p in PROFESSIONS if p in t]
    if profs:
        f["professions"] = profs
        said.append(", ".join(profs))
    if re.search(r"\bexpat", t):
        f["expats_only"], f["citizens_only"] = True, False
        said.append("expatriates")
    elif re.search(r"\bcitizens?\b|\blocals?\b|\bemiratis?\b|\bnationals?\b", t):
        f["citizens_only"], f["expats_only"] = True, False
        said.append("citizens")
    aud = sanitize(current, f)
    aud["traits"] = traits(current, {k: v for k, pattern, v in TRAIT_WORDS if re.search(pattern, t)})
    if any(v is not None for v in aud["traits"].values()) and aud["traits"] != (current.get("traits") or {}):
        said.append("adjusted how the crowd behaves")
    groups = [(name, desc, st) for name, (pattern, desc, st) in SEGMENT_WORDS.items() if re.search(pattern, t)]
    if len(groups) >= 2:
        aud["segments"] = segments([{"name": n, "description": d, "filters": {"stances": st}} for n, d, st in groups], current.get("segments"))
        said.append("comparing " + " vs ".join(n.lower() for n, _, _ in groups))
    prev = (current.get("brief") or "").strip()
    sep = " " if prev[-1:] in ".!?" else ". "
    aud["brief"] = (f"{prev}{sep}{message.strip()}" if prev else message.strip())[-BRIEF_MAX:]
    reply = (f"Set {'; '.join(said)}. " if said else "No filters matched, so the whole population stays in. ") + \
        "The rest of your description shapes how every agent thinks and talks."
    return {"audience": aud, "reply": reply, "mode": "keywords"}
