"""Per-process LRU of 1M-row projections (≈30 MB each). Evicted entries are recomputed from the
surfaces stored in simulation.results, so any API replica can answer population queries."""
from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict

import numpy as np

_lru: OrderedDict[str, dict] = OrderedDict()
_lock = threading.Lock()
MAX = 3


def put(sim_id: str, preds: dict, mask: np.ndarray) -> None:
    with _lock:
        cur = _lru.get(sim_id, {"preds": {}, "mask": mask})
        cur["preds"].update(preds)
        cur["mask"] = mask
        _lru[sim_id] = cur
        _lru.move_to_end(sim_id)
        while len(_lru) > MAX:
            _lru.popitem(last=False)


async def get(sim_id: str, results: dict, audience: dict) -> dict | None:
    with _lock:
        if sim_id in _lru:
            _lru.move_to_end(sim_id)
            return _lru[sim_id]
    if not results or "models" not in results:
        return None
    from app.services.population import get_population

    from .projection import Surface, project_population
    pop = await get_population()
    preds = {}
    for v, m in results["models"].items():
        tvv = np.array((results.get("topic_vectors") or {}).get(v, results["topic_vector"]), np.float32)
        preds[v] = await asyncio.to_thread(project_population, pop, Surface.from_json(m), tvv, results.get("platform"))
    put(sim_id, preds, pop.mask(audience))
    return _lru[sim_id]
