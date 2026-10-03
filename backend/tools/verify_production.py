"""CI smoke check for native vector queries and distributed connector exclusion. Test environments only."""
import asyncio
import uuid

from sqlalchemy import select

from app.core.config import settings
from app.core.redis import close_redis, get_redis
from app.db.session import engine, session_scope
from app.models import Signal, SignalEmbedding
from app.services.datapool.limits import source_slot
from app.services.datapool.retrieval import embed


async def main():
    if settings.env != "test" or settings.is_sqlite or not settings.redis_url:
        raise RuntimeError("Requires a dedicated test PostgreSQL and Redis environment")
    async with session_scope() as s:
        signal = Signal(source="ci", kind="trend", region="SA", title="gaming esports")
        s.add(signal)
        await s.flush()
        vector = SignalEmbedding(id="ci-" + uuid.uuid4().hex, signal_id=signal.id, model="local-hash-v1", vector=embed(signal.title).tolist())
        s.add(vector)
        await s.flush()
        closest = (await s.execute(select(SignalEmbedding).where(SignalEmbedding.id == vector.id)
            .order_by(SignalEmbedding.vector.cosine_distance(embed("gaming esports").tolist())).limit(1))).scalar_one()
        assert closest.id == vector.id
        await s.rollback()
    assert await get_redis().ping()
    key = "ci-" + uuid.uuid4().hex
    async with source_slot(key) as available:
        assert available
        async with source_slot(key) as blocked:
            assert not blocked
    await close_redis()
    await engine.dispose()
    print("Native PostgreSQL vector query and Redis connector exclusion passed")


if __name__ == "__main__":
    asyncio.run(main())
