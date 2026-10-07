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
    # Extra dimensions are namespaced so old caches/row ids remain readable.
    np.savez(tmp, **{f: getattr(pop, f) for f in FIELDS}, **{"uae__" + k: v for k, v in pop.uae.items()})
    os.replace(tmp, _path(version_id))
    return pop


def load_from_disk(version_id: str, size: int, seed: int, priors: dict | None) -> Population:
    from .regions import apply_priors
    from .uae import placeholder_provenance
    from .uae import seed as seed_uae
    with np.load(_path(version_id)) as z:
        pop = Population(n=size, seed=seed, version=version_id, regions=apply_priors(priors), **{f: z[f] for f in FIELDS})
        pop.provenance = (priors or {}).get("_provenance") or placeholder_provenance()
        extras = {k[5:]: z[k] for k in z.files if k.startswith("uae__")}
        if extras:
            pop.uae = extras
        else:
            seed_uae(pop)
        return pop


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
        from app.services.sources import ensure_sources
        await ensure_sources(s)
        v = (await s.execute(select(PopulationVersion).where(PopulationVersion.is_active.is_(True)))).scalar_one_or_none()
        if v is None:
            from .uae import placeholder_provenance
            provenance = placeholder_provenance()
            v = PopulationVersion(id="base", label="Base priors", size=settings.population_size, seed=settings.population_seed,
                                  priors={}, status="ready", is_active=True, source_ids=provenance["source_ids"],
                                  attribute_confidence=provenance["attribute_confidence"], coverage_gaps=provenance["coverage_gaps"])
            s.add(v)
        return v


async def get_population(version_id: str | None = None) -> Population:
    if version_id:
        async with session_scope() as s:
            v = await s.get(PopulationVersion, version_id)
        if not v:
            raise ValueError("Population version no longer exists")
    else:
        v = await active_version()
    from app.models import DataSource
    from app.services.population.uae import PLACEHOLDER_ID
    from app.services.sources import eligible
    async with session_scope() as s:
        for source_id in v.source_ids or []:
            if source_id != PLACEHOLDER_ID:
                source = await s.get(DataSource, source_id)
                if not source or not eligible(source):
                    raise ValueError("Population source approval was withdrawn; rebuild or activate an approved version")
    pop = await asyncio.to_thread(get_sync, v.id, v.size, v.seed, v.priors)
    if not v.stats:
        async with session_scope() as s:
            row = await s.get(PopulationVersion, v.id)
            if row is not None and not row.stats:
                row.stats = await asyncio.to_thread(stats, pop)
    return pop


def cached() -> Population | None:
    return next(iter(_cache.values()), None)
