"""Background jobs. Production: arq workers on Redis (horizontally scalable). Dev: in-process tasks."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from app.core.config import settings
from app.core.redis import get_redis

log = logging.getLogger("kruvim.jobs")
_pool = None
_local_sem: asyncio.Semaphore | None = None
_local_tasks: dict[str, asyncio.Task] = {}


async def drain() -> None:
    """Wait for local jobs and any jobs they enqueue, including post-run side effects."""
    if settings.redis_url:
        raise RuntimeError("Local queue draining is unavailable with Redis workers")
    current = asyncio.current_task()
    while pending := [task for task in _local_tasks.values() if task is not current]:
        await asyncio.gather(*(asyncio.shield(task) for task in pending))


async def _arq_pool():
    global _pool
    if _pool is None:
        from arq import create_pool
        from arq.connections import RedisSettings
        _pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    return _pool


async def enqueue(name: str, *, delay: float = 0, **kwargs) -> str:
    if settings.serverless and not settings.redis_url:
        from app.services.cloud_jobs import enqueue as cloud_enqueue
        return await cloud_enqueue(name, delay, kwargs)
    job_id = f"{name}:{uuid.uuid4().hex[:12]}"
    if settings.redis_url:
        pool = await _arq_pool()
        queue = "kruvim:connectors" if name == "run_connector" else "arq:queue"
        await pool.enqueue_job(name, _job_id=job_id, _defer_by=delay, _queue_name=queue, **kwargs)
        return job_id
    global _local_sem
    if _local_sem is None:
        _local_sem = asyncio.Semaphore(settings.worker_max_jobs)
    from app.workers import tasks

    fn = getattr(tasks, name)

    async def run():
        try:
            if delay:
                await asyncio.sleep(delay)
            async with _local_sem:
                await fn({"job_id": job_id}, **kwargs)
        except Exception:
            log.exception("local job failed", extra={"job": name})
        finally:
            _local_tasks.pop(job_id, None)

    _local_tasks[job_id] = asyncio.create_task(run())
    return job_id


# ---- per-simulation control channel (pause / resume / stop / inject) ---------------------------------
_local_ctl: dict[str, list[dict]] = {}


async def send_control(sim_id: str, cmd: dict) -> None:
    if settings.serverless and not settings.redis_url:
        from app.db.session import session_scope
        from app.models import CloudJob
        async with session_scope() as s:
            s.add(CloudJob(name="simulation_control", payload={"sim_id": sim_id, "command": cmd}))
        return
    r = get_redis()
    if r is not None:
        await r.rpush(f"simctl:{sim_id}", json.dumps(cmd))
        await r.expire(f"simctl:{sim_id}", 86400)
    else:
        _local_ctl.setdefault(sim_id, []).append(cmd)


async def drain_control(sim_id: str) -> list[dict]:
    if settings.serverless and not settings.redis_url:
        from sqlalchemy import select

        from app.db.session import session_scope
        from app.models import CloudJob
        async with session_scope() as s:
            rows = (await s.execute(select(CloudJob).where(CloudJob.name == "simulation_control", CloudJob.status == "pending",
                CloudJob.payload["sim_id"].as_string() == sim_id).order_by(CloudJob.created_at).with_for_update())).scalars().all()
            for row in rows:
                row.status = "done"
            return [row.payload["command"] for row in rows]
    r = get_redis()
    if r is not None:
        out = []
        while True:
            raw = await r.lpop(f"simctl:{sim_id}")
            if raw is None:
                return out
            out.append(json.loads(raw))
    return _local_ctl.pop(sim_id, [])


async def queue_depth() -> dict:
    if settings.serverless and not settings.redis_url:
        from sqlalchemy import func, select

        from app.db.session import session_scope
        from app.models import CloudJob
        async with session_scope() as s:
            count = (await s.execute(select(func.count()).select_from(CloudJob).where(
                CloudJob.status == "pending", CloudJob.name != "simulation_control"))).scalar()
        return {"mode": "supabase", "queued": count}
    r = get_redis()
    if r is None:
        return {"mode": "in-process", "running": len(_local_tasks)}
    return {"mode": "redis", "queued": int(await r.zcard("arq:queue"))}
