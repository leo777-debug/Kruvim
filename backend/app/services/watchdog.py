"""Bound every workflow stage and recover orphaned jobs, with an injectable clock."""
import asyncio
from contextvars import ContextVar
from datetime import timedelta
from functools import wraps

from sqlalchemy import or_, select, update

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Simulation
from app.services.events import bus

REASON = "This test took too long or its worker stopped. Retry the test to start again."
job_lease = ContextVar("kruvim_job_lease", default=None)


async def fail_expired(sim_id, token):
    async with session_scope() as s:
        row = await s.get(Simulation, sim_id)
        if not row or row.execution_token != token:
            return
        row.status, row.error, row.report_status = "failed", REASON, "failed"
    await bus.publish(sim_id, "simulation.failed", {"message": REASON})


def bounded_job(fn):
    @wraps(fn)
    async def wrapper(ctx, sim_id, **kw):
        from app.db.base import new_id
        token = new_id()
        inherited = job_lease.set(None)
        async with session_scope() as s:
            row = await s.get(Simulation, sim_id)
            if not row:
                job_lease.reset(inherited)
                return
            row.execution_token = token
            row.job_deadline = utcnow() + timedelta(seconds=settings.simulation_max_duration_seconds)
        job_lease.set((sim_id, token))
        try:
            async with asyncio.timeout(settings.simulation_max_duration_seconds):
                return await fn(ctx, sim_id, **kw)
        except (TimeoutError, asyncio.CancelledError):
            job_lease.set(None)
            await fail_expired(sim_id, token)
            raise
        finally:
            job_lease.set(None)
            async with session_scope() as s:
                await s.execute(update(Simulation).where(Simulation.id == sim_id, Simulation.execution_token == token).values(job_deadline=None))
            job_lease.reset(inherited)
    return wrapper


async def check(now=None):
    now = now or utcnow()
    async with session_scope() as s:
        rows = (await s.execute(select(Simulation).where(
            or_(Simulation.status.in_(["building_graph", "preparing", "queued", "running", "paused"]),
                Simulation.report_status.in_(["queued", "running"])),
            or_(Simulation.job_deadline <= now,
                (Simulation.job_deadline.is_(None)) & (Simulation.updated_at < now - timedelta(seconds=settings.simulation_max_duration_seconds)))))).scalars().all()
    for row in rows:
        from app.services import jobs
        if settings.redis_url and row.job_id:
            from arq.jobs import Job
            # Ask a live worker to cancel before making the test retryable.
            try:
                await Job(row.job_id, await jobs._arq_pool()).abort(timeout=2)
            except TimeoutError:
                pass  # The database fence below also blocks a slow worker's later commits.
        elif row.job_id in jobs._local_tasks:
            task = jobs._local_tasks[row.job_id]
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await fail_expired(row.id, row.execution_token)
        async with session_scope() as s:
            await s.execute(update(Simulation).where(Simulation.id == row.id, Simulation.execution_token == row.execution_token)
                            .values(execution_token=None))
    return len(rows)
