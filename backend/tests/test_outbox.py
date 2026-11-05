from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import CloudJob, Project, Simulation
from app.services import jobs, outbox
from app.workers import tasks


async def test_delivery_retries_after_lost_redis_ack_without_executing_twice(auth, monkeypatch):
    workspace = auth[1]["orgs"][0]["id"]
    async with session_scope() as s:
        project = Project(org_id=workspace, name="Outbox fixture")
        s.add(project)
        await s.flush()
        sim = Simulation(org_id=workspace, project_id=project.id, status="building_graph")
        s.add(sim)
        await s.flush()
        sim_id = sim.id
        with monkeypatch.context() as config:
            config.setattr(settings, "redis_url", "redis://unused")
            job_id = await jobs.commit_and_enqueue(s, "build_graph", simulation=sim, sim_id=sim.id)

    pool = AsyncMock()
    pool.enqueue_job.side_effect = [ConnectionError("response lost"), None, None]
    with pytest.raises(ConnectionError):
        await outbox.deliver(pool)
    async with session_scope() as s:
        assert (await s.get(CloudJob, job_id)).status == "redis_pending"
        assert (await s.get(Simulation, sim_id)).job_id == job_id

    await outbox.deliver(pool)
    async with session_scope() as s:
        row = await s.get(CloudJob, job_id)
        assert row.status == "redis_queued"
        row.updated_at = utcnow() - timedelta(minutes=2)
    await outbox.deliver(pool)
    assert [call.kwargs["_job_id"] for call in pool.enqueue_job.await_args_list] == [job_id] * 3

    handler = AsyncMock(return_value=False)
    monkeypatch.setattr(tasks, "build_graph", handler)
    for _ in range(2):
        await outbox.run_outbox_job({"job_id": job_id}, job_id)
    handler.assert_awaited_once()
    async with session_scope() as s:
        job = await s.get(CloudJob, job_id)
        assert (job.status, job.error, job.attempts) == ("error", "TaskFailed", 1)


async def test_rolled_back_work_cannot_reach_redis(auth):
    async with session_scope() as s:
        job_id = outbox.stage(s, "run_survey", {"survey_id": "rolled-back"})
        await s.rollback()
    pool = AsyncMock()
    await outbox.deliver(pool)
    pool.enqueue_job.assert_not_awaited()
    async with session_scope() as s:
        assert (await s.execute(select(CloudJob).where(CloudJob.id == job_id))).scalar_one_or_none() is None
