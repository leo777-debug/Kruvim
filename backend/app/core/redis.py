"""Shared Redis connection (None in single-process dev mode)."""
from __future__ import annotations

from redis.asyncio import Redis

from .config import settings

_client: Redis | None = None


def get_redis() -> Redis | None:
    global _client
    if not settings.redis_url:
        return None
    if _client is None:
        _client = Redis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
