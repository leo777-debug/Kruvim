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
