"""Barometer / survey import → per-region marginals → population priors.

Works with any respondent-level CSV (Arab Barometer, Pew Global Attitudes, World Values Survey,
census microdata). The user maps columns once:

    {"country_col": "COUNTRY", "weight_col": "WT", "age_col": "Q1001", "sex_col": "Q1002", "male_values": ["1", "Male"],
     "education_col": "EDU", "education_map": {"1": 0, "2": 0, "3": 1, "4": 2, "5": 3},
     "attitudes": {"religiosity": {"col": "Q609", "min": 1, "max": 4, "reverse": true}, ...},
     "country_map": {"21": "EG"}}   # optional; names / ISO codes are recognised automatically
"""
from __future__ import annotations

import csv
import io
import math
from collections import defaultdict

from .regions import AGE_BANDS, REGION_CODES

COUNTRY_ALIASES = {
    "AE": ["ae", "are", "uae", "united arab emirates", "emirates", "الإمارات"],
    "SA": ["sa", "sau", "ksa", "saudi arabia", "saudi", "السعودية"],
    "EG": ["eg", "egy", "egypt", "مصر"],
    "JO": ["jo", "jor", "jordan", "الأردن"],
    "MA": ["ma", "mar", "morocco", "المغرب"],
    "US": ["us", "usa", "united states", "united states of america", "america"],
    "GB": ["gb", "gbr", "uk", "united kingdom", "great britain", "britain"],
    "IN": ["in", "ind", "india"],
}
_ALIAS = {a: code for code, al in COUNTRY_ALIASES.items() for a in al}


def sniff(raw: bytes, max_preview: int = 8) -> dict:
    text = raw.decode("utf-8-sig", errors="replace")
    sample = text[:20000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows = list(reader)
    if not rows:
        raise ValueError("The file is empty.")
    header = [h.strip() for h in rows[0]]
    body = rows[1:]
    return {"columns": header, "preview": body[:max_preview], "rows": len(body), "delimiter": dialect.delimiter}


def _num(v):
    try:
        x = float(str(v).strip())
        return None if math.isnan(x) else x
    except (TypeError, ValueError):
        return None


def summarize(raw: bytes, mapping: dict) -> dict:
    meta = sniff(raw, 0)
    text = raw.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=meta["delimiter"])
    cmap = {str(k).strip().lower(): v for k, v in (mapping.get("country_map") or {}).items()}
    males = {str(v).strip().lower() for v in mapping.get("male_values") or ["1", "male", "m"]}
    emap = {str(k).strip().lower(): int(v) for k, v in (mapping.get("education_map") or {}).items()}
    atts = mapping.get("attitudes") or {}
    acc = defaultdict(lambda: {"w": 0.0, "n": 0, "age": [0.0] * 5, "age_w": 0.0, "male": 0.0, "sex_w": 0.0,
                               "edu": [0.0] * 4, "edu_w": 0.0, "att": defaultdict(float), "att_w": defaultdict(float)})
    unknown = defaultdict(int)
    for row in reader:
        cval = str(row.get(mapping.get("country_col", ""), "")).strip()
        code = cmap.get(cval.lower()) or _ALIAS.get(cval.lower())
        if code not in REGION_CODES:
            unknown[cval] += 1
            continue
        w = _num(row.get(mapping.get("weight_col"))) if mapping.get("weight_col") else 1.0
        if not w or w <= 0:
            w = 1.0
        a = acc[code]
        a["w"] += w
        a["n"] += 1
        age = _num(row.get(mapping.get("age_col"))) if mapping.get("age_col") else None
        if age is not None and 16 <= age <= 70:
            for k, (lo, hi) in enumerate(AGE_BANDS):
                if lo <= age <= hi:
                    a["age"][k] += w
                    a["age_w"] += w
                    break
        if mapping.get("sex_col"):
            sv = str(row.get(mapping["sex_col"], "")).strip().lower()
            if sv:
                a["sex_w"] += w
                a["male"] += w if sv in males else 0.0
        if mapping.get("education_col"):
            ev = str(row.get(mapping["education_col"], "")).strip().lower()
            if ev in emap and 0 <= emap[ev] <= 3:
                a["edu"][emap[ev]] += w
                a["edu_w"] += w
        for name, spec in atts.items():
            v = _num(row.get(spec.get("col")))
            lo, hi = float(spec.get("min", 0)), float(spec.get("max", 1))
            if v is None or hi <= lo or not (lo <= v <= hi):
                continue
            x = (v - lo) / (hi - lo)
            if spec.get("reverse"):
                x = 1 - x
            a["att"][name] += w * x
            a["att_w"][name] += w
    regions = {}
    for code, a in acc.items():
        r = {"respondents": a["n"]}
        if a["age_w"] > 0:
            r["age_bands"] = [round(x / a["age_w"], 4) for x in a["age"]]
        if a["sex_w"] > 0:
            r["male_share"] = round(a["male"] / a["sex_w"], 4)
        if a["edu_w"] > 0:
            r["education"] = [round(x / a["edu_w"], 4) for x in a["edu"]]
        if a["att_w"]:
            r["attitudes"] = {k: round(a["att"][k] / a["att_w"][k], 4) for k in a["att_w"] if a["att_w"][k] > 0}
        regions[code] = r
    return {"regions": regions, "unmatched_countries": dict(sorted(unknown.items(), key=lambda x: -x[1])[:20])}


def priors_from_summaries(summaries: list[dict], min_respondents: int = 100) -> dict:
    """Merge dataset summaries (later datasets win per field) into a priors dict for generate()."""
    priors: dict = {}
    for s in summaries:
        for code, r in (s.get("regions") or {}).items():
            if r.get("respondents", 0) < min_respondents:
                continue
            p = priors.setdefault(code, {})
            for k in ("age_bands", "male_share", "education"):
                if k in r:
                    p[k] = r[k]
            if r.get("attitudes"):
                p.setdefault("attitudes", {}).update(r["attitudes"])
    return priors
