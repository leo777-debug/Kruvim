"""Design matrix for the reaction surface, stratified sampling and persona prompts."""
from __future__ import annotations

import numpy as np

from .generator import K_INT, P, Population
from .regions import ATTITUDES, PLATFORM_LABELS, PLATFORMS, REGIONS, STANCES


def feature_names() -> list[str]:
    return ([f"region:{r['code']}" for r in REGIONS] + ["age", "age^2", "male", "citizen", "income", "education"]
            + ["openness", "conscientiousness", "extraversion", "agreeableness", "neuroticism"] + list(ATTITUDES)
            + [f"stance:{s}" for s in STANCES] + [f"uses:{p}" for p in PLATFORMS]
            + ["topic_match", "on_target_platform", "screen_time", "influence"])


def features(pop: Population, idx, topic_vec: np.ndarray, target_platform: str | None) -> np.ndarray:
    idx = np.asarray(idx)
    k = idx.size
    R = len(REGIONS)
    reg = pop.region[idx]
    a = (pop.age[idx].astype(np.float32) - 38) / 14
    cols = [
        (reg[:, None] == np.arange(R)[None, :]).astype(np.float32),
        np.stack([a, a * a, pop.male[idx].astype(np.float32), pop.citizen[idx].astype(np.float32),
                  pop.income[idx].astype(np.float32) / 4, pop.education[idx].astype(np.float32) / 3], 1),
        (pop.ocean[idx].astype(np.float32) - 0.5) / 0.15,
        (pop.attitudes[idx].astype(np.float32) - 0.5) / 0.2,
        (pop.stance[idx][:, None] == np.arange(len(STANCES))[None, :]).astype(np.float32),
    ]
    pl = pop.platforms[idx]
    cols.append(((pl[:, None] >> np.arange(P)[None, :]) & 1).astype(np.float32))
    tm = (pop.interests[idx].astype(np.float32) @ topic_vec.astype(np.float32)) * K_INT
    on_t = ((pl >> PLATFORMS.index(target_platform)) & 1).astype(np.float32) if target_platform in PLATFORMS else np.ones(k, np.float32)
    infl = np.log10(pop.followers_n[idx].astype(np.float32) + 1) - 1.0
    cols.append(np.stack([tm, on_t, pop.screen[idx].astype(np.float32), infl], 1))
    return np.concatenate(cols, 1)


def topic_match(pop: Population, idx, topic_vec: np.ndarray) -> np.ndarray:
    return (pop.interests[np.asarray(idx)].astype(np.float32) @ topic_vec.astype(np.float32)) * K_INT


def stratified_sample(pop: Population, mask: np.ndarray, n: int, rng: np.random.Generator, exclude=None) -> np.ndarray:
    """Proportional allocation over region x age band x stance (largest remainder); >=1 per stratum
    holding >= 0.5% of the audience."""
    idx = np.flatnonzero(mask)
    if exclude is not None and len(exclude):
        idx = np.setdiff1d(idx, np.asarray(exclude))
    if idx.size == 0:
        return idx
    n = min(n, idx.size)
    key = (pop.region[idx].astype(np.int32) * 5 + pop.age_band[idx]) * len(STANCES) + pop.stance[idx]
    _, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    share = cnt / cnt.sum()
    quota = share * n
    alloc = np.floor(quota).astype(int)
    alloc[(share >= 0.005) & (alloc == 0)] = 1
    rem = n - alloc.sum()
    if rem > 0:
        for j in np.argsort(-(quota - np.floor(quota)))[:rem]:
            alloc[j] += 1
    while alloc.sum() > n:
        alloc[np.argmax(alloc)] -= 1
    out = []
    for s, c in enumerate(alloc):
        if c > 0:
            members = idx[inv == s]
            out.append(rng.choice(members, size=min(c, members.size), replace=False))
    return np.concatenate(out) if out else np.array([], dtype=np.int64)


def persona_text(p: dict, platform_label: str = "social media") -> str:
    oc, at = p["ocean"], p.get("attitudes", {})
    ints = ", ".join(f'{x["label"]} ({x["w"]:.2f})' for x in p["interests"])
    lvl = lambda v: "high" if v > 0.66 else "moderate" if v > 0.33 else "low"  # noqa: E731
    return (
        f"{p.get('name', 'Persona')} (@{p.get('handle', p['id'])}), persona #{p['id']}\n"
        f"- {p['age']}, {p['gender']}, {p['origin']}, lives in {p['city']} ({p['region_name']})\n"
        f"- Speaks: {p['language']}\n"
        f"- Education: {p['education']}; work: {p['profession']}; income: {p['income']} for their country\n"
        f"- Personality (0-1): openness {oc['openness']}, conscientiousness {oc['conscientiousness']}, extraversion "
        f"{oc['extraversion']}, agreeableness {oc['agreeableness']}, neuroticism {oc['neuroticism']}\n"
        + (f"- Values: religiosity {lvl(at.get('religiosity', 0.5))}, trust in media {lvl(at.get('media_trust', 0.5))}, "
           f"interest in politics {lvl(at.get('political_interest', 0.5))}\n" if at else "")
        + f"- Uses weekly: {', '.join(p['platforms']) or 'almost no social media'}; screen time: {p['screen_time']}\n"
        f"- Strongest interests: {ints}\n"
        f"- Disposition toward new content: {p['stance']}\n"
        f"- Follows {p['follows']} accounts; {p['followers']} followers\n"
        f"- Encounters content on: {platform_label}"
    )


def platform_label(key: str | None) -> str:
    return PLATFORM_LABELS.get(key or "", "social media")
