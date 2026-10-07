"""Simulation event bus.

Every event is persisted (sim_events, append-only, unique (simulation_id, seq)) and fanned out:
Redis pub/sub across API replicas in production, in-process queues in dev. Clients replay from any
seq and then follow live, so reconnects and late joiners never miss anything."""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from collections.abc import AsyncIterator

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.redis import get_redis
from app.db.session import session_scope
from app.models import SimEvent

TERMINAL = {"simulation.completed", "simulation.failed", "simulation.cancelled", "stream.end"}


class EventBus:
    def __init__(self):
        self._local: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._seq: dict[str, int] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def _next_seq(self, s, sim_id: str) -> int:
        if sim_id not in self._seq:
            self._seq[sim_id] = int((await s.execute(select(func.coalesce(func.max(SimEvent.seq), 0)).where(SimEvent.simulation_id == sim_id))).scalar())
        self._seq[sim_id] += 1
        return self._seq[sim_id]

    async def publish(self, sim_id: str, type_: str, payload: dict | None = None) -> dict:
        payload = payload or {}
        async with self._locks[sim_id]:
            for attempt in range(3):
                try:
                    async with session_scope() as s:
                        seq = await self._next_seq(s, sim_id)
                        s.add(SimEvent(simulation_id=sim_id, seq=seq, type=type_, payload=payload))
                    break
                except IntegrityError:
                    self._seq.pop(sim_id, None)    # another writer advanced the sequence; reload
                    if attempt == 2:
                        raise
        ev = {"seq": seq, "type": type_, "payload": payload, "t": round(time.time(), 3)}
        msg = json.dumps(ev, default=str)
        r = get_redis()
        if r is not None:
            await r.publish(f"sim:{sim_id}", msg)
        else:
            for q in list(self._local[sim_id]):
                q.put_nowait(msg)
        return ev

    async def stream(self, sim_id: str, after: int = 0, follow: bool = True) -> AsyncIterator[str]:
        """Yields JSON strings. Replays persisted events with seq > after, then follows live."""
        r = get_redis()
        pubsub = None
        q: asyncio.Queue | None = None
        if follow:
            if r is not None:
                pubsub = r.pubsub()
                await pubsub.subscribe(f"sim:{sim_id}")
            else:
                q = asyncio.Queue()
                self._local[sim_id].add(q)
        try:
            last = after
            ended = False
            while True:   # replay in pages
                async with session_scope() as s:
                    rows = (await s.execute(select(SimEvent).where(SimEvent.simulation_id == sim_id, SimEvent.seq > last)
                                            .order_by(SimEvent.seq).limit(500))).scalars().all()
                for row in rows:
                    last = row.seq
                    ended = ended or row.type in TERMINAL
                    yield json.dumps({"seq": row.seq, "type": row.type, "payload": row.payload,
                                      "t": row.created_at.timestamp() if row.created_at else None}, default=str)
                if len(rows) < 500:
                    break
            if not follow:
                return
            idle = 0.0
            while True:
                msg = None
                if pubsub is not None:
                    m = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                    msg = m["data"] if m else None
                else:
                    try:
                        msg = await asyncio.wait_for(q.get(), timeout=1.0)
                    except TimeoutError:
                        msg = None
                if msg is None:
                    idle += 1.0
                    if idle >= 15:
                        idle = 0
                        yield ""   # keep-alive marker for the SSE layer
                    continue
                idle = 0
                ev = json.loads(msg)
                if ev["seq"] <= last:
                    continue
                last = ev["seq"]
                yield msg
        finally:
            if pubsub is not None:
                await pubsub.unsubscribe(f"sim:{sim_id}")
                await pubsub.aclose()
            if q is not None:
                self._local[sim_id].discard(q)


bus = EventBus()
