"""Synthetic population: N agents as columnar numpy arrays + a heavy-tailed, homophilous follow graph.

Agents are rows of data. The LLM only speaks for sampled voice agents; crowd agents act through a
statistical policy and every row receives a projected reaction (see simulation/projection.py).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import numpy as np

from .names import name_for
from .regions import (
    AGE_BAND_LABELS,
    AGE_BANDS,
    ATTITUDES,
    EDUCATION,
    GENDERS,
    INCOME_LABELS,
    INTEREST_LABELS,
    INTERESTS,
    PLATFORM_LABELS,
    PLATFORMS,
    PROFESSIONS,
    REGIONS,
    STANCES,
    apply_priors,
)

log = logging.getLogger("kruvim.population")

P = len(PLATFORMS)
K_INT = len(INTERESTS)

PLATFORM_AGE = {
    "tiktok": [1.35, 1.00, 0.75, 0.50, 0.30], "instagram": [1.20, 1.00, 0.85, 0.65, 0.45],
    "youtube": [1.05, 1.00, 0.97, 0.92, 0.85], "x": [1.00, 1.00, 0.90, 0.75, 0.60],
    "facebook": [0.60, 0.90, 1.05, 1.15, 1.15], "snapchat": [1.35, 1.00, 0.65, 0.40, 0.20],
    "linkedin": [0.40, 1.00, 1.00, 0.85, 0.50], "reddit": [1.30, 1.20, 0.90, 0.60, 0.40],
}
INTEREST_AGE = {
    "gaming": [1.8, 1.2, 0.8, 0.5, 0.3], "comedy": [1.3, 1.1, 1.0, 0.9, 0.8], "music": [1.4, 1.1, 0.9, 0.8, 0.7],
    "family": [0.3, 1.0, 1.6, 1.4, 1.1], "news_politics": [0.6, 0.9, 1.1, 1.3, 1.5], "finance": [0.6, 1.3, 1.3, 1.1, 0.9],
    "religion": [0.8, 0.9, 1.0, 1.2, 1.4], "fashion_beauty": [1.3, 1.2, 1.0, 0.8, 0.6],
    "fitness_health": [1.1, 1.2, 1.1, 1.0, 1.0], "education": [1.4, 1.1, 0.9, 0.8, 0.8],
}
MENA = {"AE", "SA", "EG", "JO", "MA"}
OCEAN_TRAITS = ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"]
FIELDS = ["region", "age", "age_band", "male", "citizen", "origin", "education", "income", "profession", "ocean",
          "attitudes", "platforms", "screen", "interests", "stance", "lang", "infl", "follows_n", "fol_ptr", "fol_idx",
          "followers_n"]


@dataclass
class Population:
    n: int
    seed: int
    version: str
    regions: list
    region: np.ndarray
    age: np.ndarray
    age_band: np.ndarray
    male: np.ndarray
    citizen: np.ndarray
    origin: np.ndarray
    education: np.ndarray
    income: np.ndarray
    profession: np.ndarray
    ocean: np.ndarray
    attitudes: np.ndarray
    platforms: np.ndarray
    screen: np.ndarray
    interests: np.ndarray
    stance: np.ndarray
    lang: np.ndarray
    infl: np.ndarray
    follows_n: np.ndarray
    fol_ptr: np.ndarray
    fol_idx: np.ndarray
    followers_n: np.ndarray

    def uses(self, platform: str) -> np.ndarray:
        return (self.platforms & (1 << PLATFORMS.index(platform))) > 0

    def mask(self, f: dict | None) -> np.ndarray:
        f = f or {}
        m = np.ones(self.n, dtype=bool)
        codes = f.get("regions")
        if codes:
            ids = [i for i, r in enumerate(REGIONS) if r["code"] in set(codes)]
            m &= np.isin(self.region, np.array(ids, dtype=np.int8))
        if f.get("age_min") not in (None, ""):
            m &= self.age >= int(f["age_min"])
        if f.get("age_max") not in (None, ""):
            m &= self.age <= int(f["age_max"])
        g = f.get("genders")
        if g and len(g) == 1:
            m &= self.male == (g[0] == "male")
        if f.get("citizens_only"):
            m &= self.citizen
        if f.get("platforms"):
            pm = np.zeros(self.n, dtype=bool)
            for p in f["platforms"]:
                if p in PLATFORMS:
                    pm |= self.uses(p)
            m &= pm
        if f.get("stances"):
            m &= np.isin(self.stance, np.array([STANCES.index(s) for s in f["stances"] if s in STANCES], dtype=np.int8))
        if f.get("education_min") not in (None, ""):
            m &= self.education >= int(f["education_min"])
        if f.get("interests"):
            ks = [INTERESTS.index(k) for k in f["interests"] if k in INTERESTS]
            if ks:
                m &= self.interests[:, ks].astype(np.float32).sum(1) >= 0.15
        if f.get("professions"):
            m &= np.isin(self.profession, np.array([PROFESSIONS.index(x) for x in f["professions"] if x in PROFESSIONS], dtype=np.int8))
        if f.get("incomes"):
            m &= np.isin(self.income, np.array([INCOME_LABELS.index(x) for x in f["incomes"] if x in INCOME_LABELS], dtype=np.int8))
        if f.get("expats_only"):
            m &= ~self.citizen
        for k, (lo, hi) in (f.get("ocean") or {}).items():
            if k in OCEAN_TRAITS:
                col = self.ocean[:, OCEAN_TRAITS.index(k)].astype(np.float32)
                m &= (col >= float(lo)) & (col <= float(hi))
        return m

    def persona(self, i: int) -> dict:
        i = int(i)
        reg = self.regions[int(self.region[i])]
        o = int(self.origin[i])
        origin = reg["citizen_label"] if o == 0 else reg["expat_labels"][o - 1]
        langs = reg["languages"]
        lang = langs[int(self.lang[i]) % len(langs)]
        plats = [PLATFORM_LABELS[p] for k, p in enumerate(PLATFORMS) if int(self.platforms[i]) & (1 << k)]
        top = np.argsort(-self.interests[i].astype(np.float32))[:3]
        interests = [{"key": INTERESTS[k], "label": INTEREST_LABELS[INTERESTS[k]], "w": round(float(self.interests[i, k]), 2)} for k in top]
        oc = [round(float(x), 2) for x in self.ocean[i]]
        at = [round(float(x), 2) for x in self.attitudes[i]]
        male = bool(self.male[i])
        name, handle = name_for(i, reg["code"], origin, male)
        return {
            "id": i, "name": name, "handle": handle, "age": int(self.age[i]), "age_band": AGE_BAND_LABELS[int(self.age_band[i])],
            "gender": GENDERS[int(male)], "region": reg["code"], "region_name": reg["name"], "city": reg["city"],
            "origin": origin, "citizen": bool(self.citizen[i]), "language": lang,
            "education": EDUCATION[int(self.education[i])], "income": INCOME_LABELS[int(self.income[i])],
            "profession": PROFESSIONS[int(self.profession[i])],
            "ocean": dict(zip(["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"], oc)),
            "attitudes": dict(zip(ATTITUDES, at)), "platforms": plats,
            "screen_time": "heavy" if self.screen[i] > 0.66 else "moderate" if self.screen[i] > 0.33 else "light",
            "interests": interests, "stance": STANCES[int(self.stance[i])],
            "follows": int(self.follows_n[i]), "followers": int(self.followers_n[i]),
        }

    def followers_of(self, i: int) -> np.ndarray:
        return self.fol_idx[self.fol_ptr[i]:self.fol_ptr[i + 1]]


def _clip01(x, lo=0.02, hi=0.98):
    return np.clip(x, lo, hi)


def generate(n: int, seed: int, priors: dict | None = None, version: str = "default") -> Population:
    t0 = time.time()
    regions = apply_priors(priors)
    R = len(regions)
    rng = np.random.default_rng(seed)
    w = np.array([r["weight"] for r in regions], dtype=np.float64)
    region = rng.choice(R, n, p=w / w.sum()).astype(np.int8)

    age_band = np.empty(n, dtype=np.int8)
    male = np.empty(n, dtype=bool)
    citizen = np.empty(n, dtype=bool)
    origin = np.zeros(n, dtype=np.int8)
    education = np.empty(n, dtype=np.int8)
    lang = np.zeros(n, dtype=np.int8)
    attitudes = np.empty((n, 3), dtype=np.float32)
    for r, reg in enumerate(regions):
        m = np.flatnonzero(region == r)
        k = m.size
        ab = np.array(reg["age_bands"], dtype=np.float64)
        age_band[m] = rng.choice(5, k, p=ab / ab.sum())
        male[m] = rng.random(k) < reg["male_share"]
        cit = rng.random(k) < reg["citizen_share"]
        citizen[m] = cit
        if reg["expat_mix"]:
            mix = np.array(reg["expat_mix"], dtype=np.float64)
            o = rng.choice(len(mix), k, p=mix / mix.sum()).astype(np.int8) + 1
            origin[m] = np.where(cit, 0, o)
        ed = np.array(reg["education"], dtype=np.float64)
        education[m] = rng.choice(4, k, p=ed / ed.sum())
        nl = len(reg["languages"])
        if reg["code"] == "AE":
            org = origin[m]
            lang[m] = np.select([org == 0, org == 1, org == 2], [0, 2, 0], default=1)
        else:
            primary = rng.random(k) < 0.82
            lang[m] = np.where(primary, 0, rng.integers(1, max(nl, 2), k) % nl)
        for a, key in enumerate(("religiosity", "media_trust", "political_interest")):
            mu = float(reg["attitudes"][key])
            attitudes[m, a] = np.clip(rng.beta(mu * 6 + 0.5, (1 - mu) * 6 + 0.5, k), 0.01, 0.99)

    lo = np.array([b[0] for b in AGE_BANDS])
    hi = np.array([b[1] for b in AGE_BANDS])
    age = (lo[age_band] + np.floor(rng.random(n) * (hi[age_band] - lo[age_band] + 1))).astype(np.int8)
    education = np.where(age < 19, 0, np.where(age < 22, np.minimum(education, 1), education)).astype(np.int8)
    attitudes[:, 0] = np.clip(attitudes[:, 0] + 0.002 * (age.astype(np.float32) - 35), 0.01, 0.99)

    career = 1 - np.abs(age.astype(np.float32) - 45) / 30
    latent = 0.7 * education + 1.2 * career + rng.normal(0, 0.9, n) + np.where(citizen, 0.4, 0.0)
    income = np.empty(n, dtype=np.int8)
    for r in range(R):
        m = np.flatnonzero(region == r)
        ranks = np.argsort(np.argsort(latent[m]))
        income[m] = np.minimum(4, (ranks * 5) // max(m.size, 1)).astype(np.int8)

    u = rng.random(n)
    hi_ed = education >= 2
    prof = np.where(hi_ed, rng.choice([5, 6, 4, 7, 10], n, p=[0.38, 0.14, 0.30, 0.13, 0.05]),
                    rng.choice([2, 3, 4, 7, 1, 8, 10], n, p=[0.30, 0.22, 0.16, 0.12, 0.10, 0.08, 0.02]))
    prof = np.where((prof == 8) & (age < 22), 2, prof)
    prof = np.where((age < 23) & (u < 0.62), 0, prof)
    prof = np.where((age >= 60) & (u < 0.6), 9, prof).astype(np.int8)

    a = age.astype(np.float32) - 35
    ocean = rng.normal(0.5, 0.15, (n, 5)).astype(np.float32)
    ocean[:, 0] -= 0.0015 * a
    ocean[:, 1] += 0.0025 * a
    ocean[:, 4] -= 0.0020 * a
    ocean = _clip01(ocean).astype(np.float16)

    plat = np.zeros(n, dtype=np.uint8)
    for k, p in enumerate(PLATFORMS):
        base = np.array([reg["platforms"].get(p, 0.0) for reg in regions], dtype=np.float32)[region]
        mult = np.array(PLATFORM_AGE[p], dtype=np.float32)[age_band]
        if p == "linkedin":
            mult = mult * np.where(hi_ed, 1.5, 0.45)
        pr = np.clip(base * mult, 0, 0.97)
        plat |= ((rng.random(n) < pr).astype(np.uint8) << k)
    screen = _clip01(rng.normal(0.62 - 0.008 * a, 0.18)).astype(np.float16)

    ints = rng.gamma(0.55, 1.0, (n, K_INT)).astype(np.float32)
    for key, mult in INTEREST_AGE.items():
        ints[:, INTERESTS.index(key)] *= np.array(mult, dtype=np.float32)[age_band]
    mena = np.array([r["code"] in MENA for r in regions])[region]
    ints[:, INTERESTS.index("religion")] *= np.where(mena, 1.0, 0.6) * (0.4 + 1.6 * attitudes[:, 0])
    ints[:, INTERESTS.index("news_politics")] *= 0.5 + 1.2 * attitudes[:, 2]
    gulf = np.isin(region, [i for i, r in enumerate(regions) if r["code"] in ("AE", "SA")])
    ints[:, INTERESTS.index("cars")] *= np.where(gulf, 1.4, 1.0)
    ints /= ints.sum(1, keepdims=True)
    interests = ints.astype(np.float16)

    # Anti-herd rule (hard-coded, never model-driven): exactly 1 contrarian, 1 skeptic, 1 disengaged per 10.
    pattern = np.array([3, 2, 4, 0, 0, 0, 1, 1, 1, 1], dtype=np.int8)
    stance = np.tile(pattern, n // 10 + 1)[:n][rng.permutation(n)]

    logf = 0.8 * rng.standard_normal(n) + 1.2 * (ocean[:, 2].astype(np.float32) - 0.5) + np.where(prof == 10, 1.5, 0.0)
    infl = (10 ** logf).astype(np.float32)
    follows_n = np.clip(np.round(5 + 14 * ocean[:, 2].astype(np.float32) * screen.astype(np.float32) * 1.6 + rng.poisson(2, n)),
                        2, 30).astype(np.int16)
    fol_ptr, fol_idx, followers_n = _build_graph(rng, region, age_band, infl, follows_n, R)
    log.info("population generated", extra={"duration_ms": round((time.time() - t0) * 1000)})
    return Population(n=n, seed=seed, version=version, regions=regions, region=region, age=age, age_band=age_band, male=male,
                      citizen=citizen, origin=origin, education=education, income=income, profession=prof, ocean=ocean,
                      attitudes=attitudes.astype(np.float16), platforms=plat, screen=screen, interests=interests, stance=stance,
                      lang=lang, infl=infl, follows_n=follows_n, fol_ptr=fol_ptr, fol_idx=fol_idx, followers_n=followers_n)


def _build_graph(rng, region, age_band, infl, follows_n, R):
    """60% same region+age band, 25% same region, 15% anywhere; followee drawn proportional to
    influence (exact weighted sampling over contiguous ranges) -> heavy-tailed followers."""
    n = region.size
    bucket = region.astype(np.int32) * 5 + age_band.astype(np.int32)
    order = np.argsort(bucket, kind="stable").astype(np.int32)
    cw = np.cumsum(infl[order].astype(np.float64))
    cw0 = np.concatenate([[0.0], cw])
    counts = np.bincount(bucket, minlength=R * 5)
    b_start = np.concatenate([[0], np.cumsum(counts)[:-1]])
    r_counts = np.bincount(region.astype(np.int32), minlength=R)
    r_start = np.concatenate([[0], np.cumsum(r_counts)[:-1]])
    src = np.repeat(np.arange(n, dtype=np.int32), follows_n.astype(np.int64))
    e = src.size
    u = rng.random(e)
    sb = bucket[src]
    sr = region[src].astype(np.int32)
    lo = np.where(u < 0.60, b_start[sb], np.where(u < 0.85, r_start[sr], 0)).astype(np.int64)
    size = np.maximum(np.where(u < 0.60, counts[sb], np.where(u < 0.85, r_counts[sr], n)), 1).astype(np.int64)
    hi = lo + size
    target = cw0[lo] + rng.random(e) * (cw0[hi] - cw0[lo])
    pos = np.clip(np.searchsorted(cw, target, side="right"), lo, hi - 1)
    dst = order[pos]
    keep = dst != src
    src, dst = src[keep], dst[keep]
    srt = np.argsort(dst, kind="stable")
    fol_idx = src[srt].astype(np.int32)
    followers_n = np.bincount(dst, minlength=n).astype(np.int32)
    fol_ptr = np.zeros(n + 1, dtype=np.int64)
    np.cumsum(followers_n, out=fol_ptr[1:])
    return fol_ptr, fol_idx, followers_n


def stats(pop: Population) -> dict:
    rs = np.random.default_rng(1)
    s = rs.choice(pop.n, min(200_000, pop.n), replace=False)
    fol = pop.followers_n
    return {
        "n": pop.n, "edges": int(pop.fol_idx.size),
        "regions": [{"code": r["code"], "name": r["name"], "n": int(c)}
                    for r, c in zip(pop.regions, np.bincount(pop.region.astype(np.int64), minlength=len(pop.regions)))],
        "age_bands": [{"label": lab, "share": round(float((pop.age_band[s] == k).mean()), 4)} for k, lab in enumerate(AGE_BAND_LABELS)],
        "stances": [{"label": lab, "share": round(float((pop.stance[s] == k).mean()), 4)} for k, lab in enumerate(STANCES)],
        "platforms": [{"label": PLATFORM_LABELS[p], "share": round(float(pop.uses(p)[s].mean()), 4)} for p in PLATFORMS],
        "education": [{"label": lab, "share": round(float((pop.education[s] == k).mean()), 4)} for k, lab in enumerate(EDUCATION)],
        "attitudes": {a: round(float(pop.attitudes[s, k].astype(np.float32).mean()), 3) for k, a in enumerate(ATTITUDES)},
        "followers": {str(q): int(np.percentile(fol, q)) for q in (10, 50, 90, 99, 99.9)} | {"max": int(fol.max())},
        "male_share": round(float(pop.male[s].mean()), 4),
        "incomes": INCOME_LABELS, "genders": GENDERS, "professions": PROFESSIONS,
    }
