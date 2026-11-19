"""Fixed-window rate limiting. Redis-backed in production (shared across API replicas)."""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import timedelta

from .config import settings
from .errors import RateLimited
from .redis import get_redis
from .security import sha256

_local: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))


async def hit(key: str, limit: int, window: int = 60) -> None:
    bucket = int(time.time() // window)
    backend = settings.rate_limit_backend
    r = get_redis() if backend in ("auto", "redis") else None
    if r is not None:
        k = f"rl:{sha256(f'{window}:{key}')}:{bucket}"
        n = await r.eval("local n = redis.call('INCR', KEYS[1]); if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; return n", 1, k, window + 5)
    elif backend == "database" or (backend == "auto" and (settings.is_prod or settings.serverless)):
        from sqlalchemy import delete
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from app.db.base import utcnow
        from app.db.session import SessionLocal
        from app.models import RateCounter

        async with SessionLocal() as s:
            insert = sqlite_insert if s.bind.dialect.name == "sqlite" else pg_insert
            stmt = insert(RateCounter).values(key=sha256(f"{window}:{key}"), bucket=bucket, count=1,
                expires_at=utcnow() + timedelta(seconds=window + 5))
            n = (await s.execute(stmt.on_conflict_do_update(index_elements=["key", "bucket"],
                set_={"count": RateCounter.count + 1}).returning(RateCounter.count))).scalar_one()
            await s.execute(delete(RateCounter).where(RateCounter.expires_at < utcnow()))
            await s.commit()
    else:
        b, n = _local[key]
        n = n + 1 if b == bucket else 1
        _local[key] = (bucket, n)
    if n > limit:
        raise RateLimited(f"Too many requests. Limit is {limit} per {window}s.")
