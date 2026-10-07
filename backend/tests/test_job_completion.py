import asyncio

import pytest

from app.services import jobs, monitoring
from app.workers import tasks


async def test_drain_waits_for_chained_jobs_and_side_effects(monkeypatch):
    child_started, release_child = asyncio.Event(), asyncio.Event()
    effects = []

    async def child(ctx):
        child_started.set()
        await release_child.wait()
        effects.append("alert committed")

    async def parent(ctx):
        effects.append("simulation completed")
        await jobs.enqueue("test_child")

    monkeypatch.setattr(tasks, "test_parent", parent, raising=False)
    monkeypatch.setattr(tasks, "test_child", child, raising=False)
    await jobs.enqueue("test_parent")
    draining = asyncio.create_task(jobs.drain())
    await child_started.wait()
    assert not draining.done() and effects == ["simulation completed"]
    release_child.set()
    await draining
    assert effects == ["simulation completed", "alert committed"]
    assert (await jobs.queue_depth())["running"] == 0


async def test_cancelled_local_job_leaves_no_stale_queue_entry(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def work(ctx):
        started.set()
        await release.wait()

    monkeypatch.setattr(tasks, "test_cancel", work, raising=False)
    job_id = await jobs.enqueue("test_cancel")
    task = jobs._local_tasks[job_id]
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await jobs.drain()
    assert job_id not in jobs._local_tasks


async def test_tick_passes_one_injected_time_to_both_schedulers(monkeypatch):
    from datetime import UTC, datetime
    from unittest.mock import AsyncMock

    at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    watches, reruns = AsyncMock(return_value=[]), AsyncMock(return_value=[])
    monkeypatch.setattr(monitoring, "due_watches", watches)
    monkeypatch.setattr(monitoring, "due_reruns", reruns)
    assert await monitoring.tick(now=at) == {"watches": 0, "reruns": 0}
    watches.assert_awaited_once_with(at)
    reruns.assert_awaited_once_with(at)
