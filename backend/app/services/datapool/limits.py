"""Per-source exclusion across workers and polite request spacing."""
import asyncio
import secrets
import time
from contextlib import asynccontextmanager

from app.core.config import settings
from app.core.redis import get_redis

_locks = {}
_last = {}


@asynccontextmanager
async def source_slot(key):
    redis = get_redis()
    token = secrets.token_hex(16)
    lock_key = f"connector-lock:{key}"
    if redis:
        if not await redis.set(lock_key, token, nx=True, ex=150):
            yield False
            return
    lock = _locks.setdefault(key, asyncio.Lock())
    try:
        async with lock:
            interval = settings.connector_min_interval_seconds.get(key, 1)
            if redis:
                last = float(await redis.get(f"connector-last:{key}") or 0)
            else:
                last = _last.get(key, 0)
            wait = max(0, interval - (time.time() - last))
            if wait:
                await asyncio.sleep(min(wait, 20))
            _last[key] = time.time()
            if redis:
                await redis.set(f"connector-last:{key}", str(time.time()), ex=3600)
            yield True
    finally:
        if redis:
            await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) else return 0 end", 1, lock_key, token)


_spent = {}


async def spend_quota(key, units):
    """Reserve `units` of today's (UTC) API budget for `key`; False once the budget would be exceeded.
    Keys without a configured budget are unlimited."""
    limit = settings.connector_daily_quota_units.get(key)
    if limit is None:
        return True
    day = time.strftime("%Y%m%d", time.gmtime())
    redis = get_redis()
    if redis:
        counter = f"connector-quota:{key}:{day}"
        used = await redis.incrby(counter, units)
        await redis.expire(counter, 2 * 86400)
        if used > limit:
            await redis.decrby(counter, units)
            return False
        return True
    used = _spent.get((key, day), 0)
    if used + units > limit:
        return False
    _spent[(key, day)] = used + units
    return True
