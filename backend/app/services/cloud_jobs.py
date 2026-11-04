"""Supabase-backed job delivery. pg_net sends only after the enqueue transaction commits."""
import json
import secrets
from datetime import timedelta

from fastapi import APIRouter, Request
from sqlalchemy import select, text

from app.core.config import settings
from app.core.errors import AppError, Unauthorized
from app.db.base import utcnow
from app.db.session import session_scope
from app.models.cloud import CloudJob

router = APIRouter(prefix="/internal", tags=["cloud jobs"])


def authorize(request):
    expected = "Bearer " + settings.cron_secret
    if not settings.cron_secret or not secrets.compare_digest(request.headers.get("authorization", ""), expected):
        raise Unauthorized("Invalid scheduler credentials.")


async def dispatch(s, job):
    await s.execute(text("SELECT net.http_post(url := :url, body := CAST(:body AS jsonb), "
        "headers := CAST(:headers AS jsonb), timeout_milliseconds := 300000)"), {
        "url": settings.public_url.rstrip("/") + "/api/v1/internal/jobs/" + job.id,
        "body": "{}", "headers": json.dumps({"Content-Type": "application/json", "Authorization": "Bearer " + settings.cron_secret})})


async def enqueue(name, delay, payload):
    if not settings.cron_secret:
        raise AppError("Cloud job scheduler is not configured.", status=503)
    async with session_scope() as s:
        job = CloudJob(name=name, payload=payload, due_at=utcnow() + timedelta(seconds=delay))
        s.add(job)
        await s.flush()
        if not delay:
            await dispatch(s, job)
        return job.id


@router.post("/jobs/{job_id}")
async def run_job(job_id: str, request: Request):
    authorize(request)
    async with session_scope() as s:
        job = (await s.execute(select(CloudJob).where(CloudJob.id == job_id).with_for_update(skip_locked=True))).scalar_one_or_none()
        if not job or job.status != "pending" or job.due_at > utcnow():
            return {"status": "skipped"}
        job.status, job.updated_at = "running", utcnow()
        job.attempts += 1
        name, payload = job.name, dict(job.payload)
    from app.workers import tasks
    allowed = {"build_graph", "prepare_environment", "run_simulation", "generate_report", "run_survey", "run_connector", "build_population", "resume_autopilot"}
    if name not in allowed:
        error = "Unsupported cloud job"
    else:
        try:
            await getattr(tasks, name)({"job_id": job_id}, **payload)
            error = ""
        except Exception as exc:
            import logging
            logging.getLogger("kruvim.cloud").exception("Cloud job failed")
            error = type(exc).__name__
    async with session_scope() as s:
        job = await s.get(CloudJob, job_id)
        job.status, job.error, job.updated_at = ("error" if error else "done"), error, utcnow()
    return {"status": "error" if error else "done"}


@router.api_route("/refresh", methods=["GET", "POST"])
async def refresh(request: Request):
    authorize(request)
    from app.services.library import sync_due
    await sync_due()
    from app.services.token_budget import tick
    from app.services.watchdog import check
    await check()
    await tick()
    async with session_scope() as s:
        jobs = (await s.execute(select(CloudJob).where(CloudJob.status == "pending", CloudJob.name != "simulation_control", CloudJob.due_at <= utcnow())
            .order_by(CloudJob.created_at).limit(20).with_for_update(skip_locked=True))).scalars().all()
        for job in jobs:
            await dispatch(s, job)
    return {"status": "ok", "dispatched": len(jobs)}
