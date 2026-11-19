"""Persist Redis work in PostgreSQL before handing it to an ARQ queue."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import and_, or_, select, update

from app.core.config import settings
from app.db.base import new_id, utcnow
from app.db.session import session_scope
from app.models import CloudJob, Simulation

log = logging.getLogger("kruvim.outbox")
TASKS = frozenset({
    "build_graph", "prepare_environment", "run_simulation", "generate_report",
    "run_survey", "run_connector", "build_population", "resume_autopilot",
})
STAGES = {
    "build_graph": ("status", "building_graph"),
    "prepare_environment": ("status", "preparing"),
    "run_simulation": ("status", "queued"),
    "generate_report": ("report_status", "queued"),
}


def stage(session, name, payload, delay=0):
    if name not in TASKS:
        raise ValueError(f"Unsupported queued task: {name}")
    job_id = new_id()
    session.add(CloudJob(id=job_id, name=name, payload=payload, status="redis_pending",
                         due_at=utcnow() + timedelta(seconds=delay)))
    return job_id


async def deliver(pool):
    now = utcnow()
    async with session_scope() as session:
        rows = (await session.execute(select(CloudJob).where(
            or_(
                and_(CloudJob.status == "redis_pending", CloudJob.due_at <= now),
                and_(CloudJob.status == "redis_queued", CloudJob.updated_at < now - timedelta(minutes=1)),
            ),
        ).order_by(CloudJob.updated_at, CloudJob.id).limit(20).with_for_update(skip_locked=True))).scalars().all()
        for row in rows:
            queue = "kruvim:connectors" if row.name == "run_connector" else "arq:queue"
            async with asyncio.timeout(3):
                await pool.enqueue_job("run_outbox_job", row.id, _job_id=row.id, _queue_name=queue)
            row.status, row.updated_at = "redis_queued", utcnow()


async def poll(pool):
    while True:
        try:
            await deliver(pool)
        except Exception:
            log.exception("Queue delivery failed; pending jobs will be retried")
            await asyncio.sleep(10)
        else:
            await asyncio.sleep(2)


async def run_outbox_job(ctx, job_id):
    from app.workers import tasks

    async with session_scope() as session:
        job = await session.get(CloudJob, job_id, with_for_update=True)
        if not job or job.status not in {"redis_pending", "redis_queued"}:
            return
        name, payload = job.name, dict(job.payload)
        if name in STAGES:
            field, expected = STAGES[name]
            sim = await session.get(Simulation, payload["sim_id"], with_for_update=True)
            if not sim or sim.job_id != job_id or getattr(sim, field) != expected:
                job.status, job.error, job.updated_at = "error", "StageSuperseded", utcnow()
                return
        job.status, job.updated_at = "redis_running", utcnow()
        job.attempts += 1

    error = ""
    try:
        result = await getattr(tasks, name)({**ctx, "outbox": True}, **payload)
        if result is False or isinstance(result, dict) and result.get("status") == "error":
            error = "TaskFailed"
    except BaseException as exc:
        error = type(exc).__name__
        raise
    finally:
        if error:
            log.warning("Queued job failed", extra={"job_id": job_id, "job": name, "failure": error})
        async with session_scope() as session:
            await session.execute(update(CloudJob).where(
                CloudJob.id == job_id, CloudJob.status == "redis_running",
            ).values(status="error" if error else "done", error=error, updated_at=utcnow()))


async def recover_interrupted():
    # Match the configurable ARQ timeout. Do not replay an operation
    # whose model calls, uploads or accounting might already have taken effect.
    now = utcnow()
    async with session_scope() as session:
        result = await session.execute(update(CloudJob).where(
            CloudJob.status == "redis_running", CloudJob.updated_at < now - timedelta(
                seconds=max(6 * 3600, settings.simulation_max_duration_seconds + 60) + 300),
        ).values(status="error", error="WorkerInterrupted", updated_at=now))
    if result.rowcount:
        log.warning("Recorded %s interrupted worker jobs", result.rowcount)
