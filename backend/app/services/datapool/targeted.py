"""Bounded deterministic pulls before the simulation, persisted with its tenant and run identity."""
import asyncio

from sqlalchemy import select

from app.db.session import session_scope
from app.models import DataSource, Signal
from app.services.datapool.listening import listen


async def prepare(sim_id, org_id, card, codes, snapshots):
    terms = [*(card.get("keywords") or [])[:4], *(card.get("entities") or [])[:2]]
    if not terms:
        terms = [card.get("title", "")]
    try:
        async with asyncio.timeout(20):
            await listen(terms, codes, org_id, per_source=5, simulation_id=sim_id)
    except TimeoutError:
        pass
    async with session_scope() as s:
        signals = (await s.execute(select(Signal).where(Signal.org_id == org_id, Signal.simulation_id == sim_id))).scalars().all()
        from app.services.sources import ensure_sources, signal_source
        await ensure_sources(s)
        sources = {r.key: signal_source(r) for r in (await s.execute(select(DataSource))).scalars()}
    from .retrieval import embed
    for signal in signals:
        for code, snapshot in snapshots.items():
            if signal.region not in (code, "*"):
                continue
            snapshot.setdefault("signals", []).append({"id": signal.id, "source": signal.source, "kind": signal.kind,
                "source_id": signal.source_id, "region": signal.region, "language": signal.lang,
                "nationality_groups": signal.payload.get("nationality_groups", []),
                "provenance": sources.get(signal.source, sources["placeholder_priors"]),
                "source_weight": sources.get(signal.source, {}).get("source_weight", 0),
                "title": signal.title, "summary": str(signal.payload.get("summary", ""))[:500], "url": signal.url,
                "at": signal.observed_at.isoformat(), "embedding": embed(signal.title).tolist(), "simulation_id": sim_id})
