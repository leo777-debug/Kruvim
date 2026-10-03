"""From LLM-agent answers to reactions for every agent in the population.

Ridge reaction surface (persona features → answers), deterministic residual noise per agent, bootstrap
intervals (no extra LLM calls) and an independent-cascade share simulation on the follower graph."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.services.population import Population, features
from app.services.population.regions import REGIONS

CHUNK = 131072


@dataclass
class Surface:
    targets: list
    mu: np.ndarray
    sd: np.ndarray
    W: np.ndarray
    b: np.ndarray
    sigma: np.ndarray
    lo: np.ndarray
    hi: np.ndarray
    seed: int
    lam: float
    r2: list

    def to_json(self) -> dict:
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v) for k, v in self.__dict__.items()}

    @staticmethod
    def from_json(d: dict) -> Surface:
        arr = lambda k: np.array(d[k], np.float32)  # noqa: E731
        return Surface(targets=d["targets"], mu=arr("mu"), sd=arr("sd"), W=arr("W"), b=arr("b"), sigma=arr("sigma"), lo=arr("lo"),
                       hi=arr("hi"), seed=int(d["seed"]), lam=float(d["lam"]), r2=d.get("r2", []))


def _ridge(Xs, Y, lam):
    ym = Y.mean(0)
    W = np.linalg.solve(Xs.T @ Xs + lam * np.eye(Xs.shape[1]), Xs.T @ (Y - ym))
    return W, ym


def fit(X: np.ndarray, Y: np.ndarray, targets: list[str], seed: int, lam: float = 6.0) -> Surface:
    X, Y = X.astype(np.float64), Y.astype(np.float64)
    mu, sd = X.mean(0), X.std(0)
    sd[sd < 1e-6] = 1.0
    Xs = (X - mu) / sd
    W, b = _ridge(Xs, Y, lam)
    resid = Y - (Xs @ W + b)
    var = Y.var(0)
    r2 = [round(float(1 - resid[:, j].var() / var[j]), 3) if var[j] > 1e-9 else 0.0 for j in range(Y.shape[1])]
    is_score = np.array([t in ("score", "opinion") for t in targets])
    is_seg = np.array([t.startswith("seg") for t in targets])
    lo = np.where(is_seg, 0.02, 0.0)
    hi = np.where(is_score, 10.0, np.where(is_seg, 0.999, 1.0))
    return Surface(targets, mu.astype(np.float32), sd.astype(np.float32), W.astype(np.float32), b.astype(np.float32),
                   resid.std(0).astype(np.float32), lo.astype(np.float32), hi.astype(np.float32), seed, lam, r2)


def _apply(m: Surface, X: np.ndarray, noise: np.ndarray | None) -> np.ndarray:
    P = ((X - m.mu) / m.sd) @ m.W + m.b
    if noise is not None:
        P = P + noise * (m.sigma * 0.9)
    return np.clip(P, m.lo, m.hi)


def project_idx(pop: Population, m: Surface, idx: np.ndarray, topic_vec, platform, noise_seed: int) -> np.ndarray:
    X = features(pop, idx, topic_vec, platform)
    noise = np.random.default_rng([m.seed, noise_seed]).standard_normal((idx.size, len(m.targets))).astype(np.float32)
    return _apply(m, X, noise)


def project_population(pop: Population, m: Surface, topic_vec, platform) -> np.ndarray:
    out = np.empty((pop.n, len(m.targets)), dtype=np.float16)
    for c, start in enumerate(range(0, pop.n, CHUNK)):
        idx = np.arange(start, min(pop.n, start + CHUNK))
        X = features(pop, idx, topic_vec, platform)
        noise = np.random.default_rng([m.seed, c]).standard_normal((idx.size, len(m.targets))).astype(np.float32)
        out[idx] = _apply(m, X, noise).astype(np.float16)
    return out


def project_one(pop: Population, m: Surface, topic_vec, platform, i: int) -> dict:
    c, start = i // CHUNK, (i // CHUNK) * CHUNK
    size = min(pop.n, start + CHUNK) - start
    noise = np.random.default_rng([m.seed, c]).standard_normal((size, len(m.targets))).astype(np.float32)[i - start]
    v = _apply(m, features(pop, np.array([i]), topic_vec, platform), noise[None, :])[0]
    return {t: round(float(x), 3) for t, x in zip(m.targets, v)}


def bootstrap_mean(Xv, yv, Xa, seed: int, B: int = 150, lam: float = 6.0):
    rng = np.random.default_rng(seed + 991)
    n = Xv.shape[0]
    Xv, Xa = Xv.astype(np.float64), Xa.astype(np.float64)
    means = np.empty(B)
    for b in range(B):
        k = rng.integers(0, n, n)
        X = Xv[k]
        mu, sd = X.mean(0), X.std(0)
        sd[sd < 1e-6] = 1.0
        W, ym = _ridge((X - mu) / sd, yv[k][:, None].astype(np.float64), lam)
        means[b] = float((((Xa - mu) / sd) @ W + ym).mean())
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def paired_bootstrap(d: np.ndarray, seed: int, B: int = 2000):
    rng = np.random.default_rng(seed + 7)
    ms = d[rng.integers(0, d.size, (B, d.size))].mean(1)
    return float(np.percentile(ms, 2.5)), float(np.percentile(ms, 97.5)), float((ms > 0).mean())


CASCADE = {"feed_visibility": 0.30, "intent_to_action": 0.40, "seed_fraction": 0.01, "max_steps": 10}


def _followers_of_many(pop: Population, nodes: np.ndarray) -> np.ndarray:
    starts = pop.fol_ptr[nodes]
    lens = (pop.fol_ptr[nodes + 1] - starts).astype(np.int64)
    total = int(lens.sum())
    if total == 0:
        return np.empty(0, dtype=np.int32)
    offs = np.repeat(starts - np.concatenate([[0], np.cumsum(lens)[:-1]]), lens)
    return pop.fol_idx[offs + np.arange(total)]


def cascade(pop: Population, share: np.ndarray, audience_idx: np.ndarray, seed: int, runs: int = 8, boost: float = 1.0) -> dict:
    """Independent cascade over the 1M follower graph. `boost` scales sharing by the amplification
    actually observed in the agent simulation (sim reposts per exposure vs. stated intent)."""
    a = CASCADE
    n_seed = min(int(np.clip(audience_idx.size * a["seed_fraction"], 200, 5000)), audience_idx.size)
    p_share = np.clip(share.astype(np.float32) * a["intent_to_action"] * boost, 0, 0.95)
    in_aud = np.zeros(pop.n, dtype=bool)
    in_aud[audience_idx] = True
    reaches, curves, region_counts, aud_share, seed_regions = [], [], [], [], []
    for r in range(runs):
        rng = np.random.default_rng([seed, 31, r])
        seeds = rng.choice(audience_idx, n_seed, replace=False)
        exposed = np.zeros(pop.n, dtype=bool)
        exposed[seeds] = True
        frontier = seeds
        curve = [{"step": 0, "exposed": int(n_seed), "sharers": 0}]
        sharers = 0
        for step in range(1, a["max_steps"] + 1):
            sh = frontier[rng.random(frontier.size) < p_share[frontier]]
            sharers += sh.size
            if sh.size == 0:
                break
            cand = _followers_of_many(pop, sh)
            seen = cand[rng.random(cand.size) < a["feed_visibility"]]
            new = np.unique(seen[~exposed[seen]])
            exposed[new] = True
            curve.append({"step": step, "exposed": int(exposed.sum()), "sharers": int(sharers)})
            frontier = new
            if new.size == 0:
                break
        reaches.append(int(exposed.sum()))
        seed_regions.append(np.bincount(pop.region[seeds].astype(np.int64), minlength=len(REGIONS)))
        curves.append(curve)
        region_counts.append(np.bincount(pop.region[exposed].astype(np.int64), minlength=len(REGIONS)))
        aud_share.append(float(in_aud[exposed].mean()))
    reaches = np.array(reaches)
    amp = reaches / max(n_seed, 1)
    # rough real-world scale: each agent stands for (social-media users in its region) / (agents in its region)
    per_region = np.bincount(pop.region.astype(np.int64), minlength=len(REGIONS)).astype(np.float64)
    scale = np.array([r.get("social_users_m", 0) * 1e6 for r in REGIONS]) / np.maximum(per_region, 1)
    real = np.array([float(rc @ scale) for rc in region_counts])
    seed_people = float(np.mean([float(sr @ scale) for sr in seed_regions])) if seed_regions else 0.0
    med = int(np.argsort(reaches)[len(reaches) // 2])
    return {"seeds": n_seed, "reach_median": int(np.median(reaches)), "reach_p10": int(np.percentile(reaches, 10)),
            "reach_p90": int(np.percentile(reaches, 90)), "amplification_median": round(float(np.median(amp)), 2),
            "p_amplification_over_2x": round(float((amp > 2).mean()), 3), "p_amplification_over_5x": round(float((amp > 5).mean()), 3),
            "curve": curves[med], "runs": runs, "boost": round(boost, 2),
            "region_reach": [{"code": REGIONS[k]["code"], "name": REGIONS[k]["name"], "n": int(v)}
                             for k, v in enumerate(np.mean(region_counts, 0).round().astype(int)) if v],
            "outside_audience_share": round(1 - float(np.mean(aud_share)), 3), "assumptions": a,
            "reach_runs": sorted(int(x) for x in reaches),
            "people_runs": [round(float(x)) for x in real], "seed_people": round(seed_people)}
