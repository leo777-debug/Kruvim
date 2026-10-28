"""Fixed-window rate limiting. Redis-backed in production (shared across API replicas)."""
from __future__ import annotations

import time
from collections import defaultdict

from .errors import RateLimited
from .redis import get_redis

_local: dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))


async def hit(key: str, limit: int, window: int = 60) -> None:
    bucket = int(time.time() // window)
    r = get_redis()
    if r is not None:
        k = f"rl:{key}:{bucket}"
        n = await r.incr(k)
        if n == 1:
            await r.expire(k, window + 5)
    else:
        b, n = _local[key]
        n = n + 1 if b == bucket else 1
        _local[key] = (bucket, n)
    if n > limit:
        raise RateLimited(f"Too many requests. Limit is {limit} per {window}s.")


async def count(key: str, window: int, amount: int = 1) -> int:
    """Add to a fixed-window counter and return the new total (shared across replicas when Redis is configured)."""
    bucket = int(time.time() // window)
    r = get_redis()
    if r is not None:
        k = f"ct:{key}:{bucket}"
        n = await r.incrby(k, amount)
        if n == amount:
            await r.expire(k, window + 60)
        return int(n)
    b, n = _local[f"ct:{key}"]
    n = n + amount if b == bucket else amount
    _local[f"ct:{key}"] = (bucket, n)
    return n


async def peek(key: str, window: int) -> int:
    bucket = int(time.time() // window)
    r = get_redis()
    if r is not None:
        return int(await r.get(f"ct:{key}:{bucket}") or 0)
    b, n = _local[f"ct:{key}"]
    return n if b == bucket else 0


async def add(key: str, amount: int, ttl: int) -> int:
    """Add to a named counter (the caller puts the period, e.g. the month, in the key) and return the new total."""
    r = get_redis()
    if r is not None:
        n = await r.incrby(f"sum:{key}", amount)
        if n == amount:
            await r.expire(f"sum:{key}", ttl)
        return int(n)
    _, n = _local[f"sum:{key}"]
    _local[f"sum:{key}"] = (0, n + amount)
    return n + amount


async def total(key: str) -> int:
    r = get_redis()
    if r is not None:
        return int(await r.get(f"sum:{key}") or 0)
    return _local[f"sum:{key}"][1]
