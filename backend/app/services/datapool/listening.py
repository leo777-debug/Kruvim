"""Social listening: fetch the real, current conversation about the content's topic from every
connector that supports search. Results seed the simulation as external posts."""
from __future__ import annotations

import asyncio
import logging

import httpx
from sqlalchemy import select

from app.db.session import session_scope
from app.models import Connector
from app.services.population.regions import REGIONS

from .base import UA, SignalItem
from .connectors import REGISTRY
from .runner import secrets_of, store_signals

log = logging.getLogger("kruvim.datapool")


async def listen(terms: list[str], region_codes: list[str], org_id: str | None, per_source: int = 6) -> list[dict]:
    query = " ".join(t for t in terms[:3] if t).strip()
    if not query:
        return []
    regs = [r for r in REGIONS if r["code"] in region_codes] or REGIONS[:1]
    async with session_scope() as s:
        rows = (await s.execute(select(Connector).where(Connector.key.in_([k for k, c in REGISTRY.items() if c.spec.supports_search])))).scalars().all()
    by_key: dict[str, Connector] = {}
    for r in rows:   # org-level credentials win over platform-level
        if r.org_id == org_id or (r.org_id is None and r.key not in by_key):
            by_key[r.key] = r

    async def one(key: str):
        row = by_key.get(key)
        if row is not None and not row.enabled:
            return key, []
        try:
            async with httpx.AsyncClient(headers=UA, timeout=12, follow_redirects=True) as client:
                items = await asyncio.wait_for(REGISTRY[key].search(client, query, regs, secrets_of(row), dict(row.config) if row else {},
                                                                    per_source), timeout=15)
            return key, items
        except Exception as exc:
            log.info("listening via %s failed: %s", key, exc)
            return key, []

    results = await asyncio.gather(*[one(k) for k, c in REGISTRY.items() if c.spec.supports_search])
    out = []
    for key, items in results:
        if items:
            await store_signals(f"{key}_listen", items)
        for i in items:
            out.append(_as_post(key, i))
    out.sort(key=lambda p: -(p.get("engagement") or 0))
    return out[:24]


def _as_post(key: str, i: SignalItem) -> dict:
    return {"source": key, "platform": i.payload.get("platform", key), "author": i.payload.get("author") or i.payload.get("source") or key,
            "text": i.title, "url": i.url, "lang": i.lang, "engagement": i.value or 0,
            "observed_at": i.observed_at.isoformat() if i.observed_at else None}
