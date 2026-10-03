"""Population versions on disk (npz in the shared data volume) with an in-process cache.

API replicas and workers all load the *active* version lazily; building a new version (after a
barometer calibration) happens in a worker job and flips `is_active` when done."""
from __future__ import annotations

import asyncio
import logging
import os
import threading

import numpy as np
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models import PopulationVersion

from .generator import FIELDS, Population, generate, stats

log = logging.getLogger("kruvim.population")
_cache: dict[str, Population] = {}
_lock = threading.Lock()


def _path(version_id: str) -> str:
    d = os.path.join(settings.data_dir, "population")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{version_id}.npz")


def build_to_disk(version_id: str, size: int, seed: int, priors: dict | None) -> Population:
    pop = generate(size, seed, priors, version=version_id)
    tmp = _path(version_id) + ".tmp.npz"
    np.savez(tmp, **{f: getattr(pop, f) for f in FIELDS})
    os.replace(tmp, _path(version_id))
    return pop


def load_from_disk(version_id: str, size: int, seed: int, priors: dict | None) -> Population:
    from .regions import apply_priors
    z = np.load(_path(version_id))
    return Population(n=size, seed=seed, version=version_id, regions=apply_priors(priors), **{f: z[f] for f in FIELDS})


def get_sync(version_id: str, size: int, seed: int, priors: dict | None) -> Population:
    with _lock:
        if version_id in _cache:
            return _cache[version_id]
        if os.path.exists(_path(version_id)):
            try:
                pop = load_from_disk(version_id, size, seed, priors)
            except Exception as exc:
                log.warning("population cache unreadable (%s); rebuilding", exc)
                pop = build_to_disk(version_id, size, seed, priors)
        else:
            pop = build_to_disk(version_id, size, seed, priors)
        _cache.clear()          # keep one version per process (memory)
        _cache[version_id] = pop
        return pop


async def active_version() -> PopulationVersion:
    async with session_scope() as s:
        v = (await s.execute(select(PopulationVersion).where(PopulationVersion.is_active.is_(True)))).scalar_one_or_none()
        if v is None:
            v = PopulationVersion(id="base", label="Base priors", size=settings.population_size, seed=settings.population_seed,
                                  priors={}, status="ready", is_active=True)
            s.add(v)
        return v


async def get_population() -> Population:
    v = await active_version()
    pop = await asyncio.to_thread(get_sync, v.id, v.size, v.seed, v.priors)
    if not v.stats:
        async with session_scope() as s:
            row = await s.get(PopulationVersion, v.id)
            if row is not None and not row.stats:
                row.stats = await asyncio.to_thread(stats, pop)
    return pop


def cached() -> Population | None:
    return next(iter(_cache.values()), None)
