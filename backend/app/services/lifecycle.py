"""Queueing the three run steps. Shared by the API (a person clicks) and the workers (autopilot: batch tests,
recurring re-runs and competitor monitoring chain graph -> environment -> simulation without anyone clicking)."""
from __future__ import annotations

import asyncio
from collections import defaultdict

from sqlalchemy import and_, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict
from app.models import Action, GraphEdge, GraphNode, Organization, Post, Report, SimAgent, SimEvent, Simulation
from app.services import audit, jobs
from app.services.events import bus
from app.services.providers import resolve
from app.services.quotas import check_start

LOCKED = ("building_graph", "preparing", "queued", "running", "paused")
_start_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


async def queue_graph(s: AsyncSession, sim: Simulation) -> str:
    if sim.status in LOCKED:
        raise Conflict("A step is already running for this simulation.")
    c = sim.content or {}
    if c.get("type") == "text" and not (c.get("text") or "").strip() and not c.get("asset_id"):
        raise AppError("Add the text or upload a document before building the graph.")
    for model in (GraphEdge, GraphNode, SimEvent, Action, Post, SimAgent):
        await s.execute(delete(model).where(model.simulation_id == sim.id))
    sim.status, sim.step, sim.error, sim.results, sim.report_status, sim.progress = "building_graph", 1, None, {}, "none", {}
    await s.commit()
    bus._seq.pop(sim.id, None)
    sim.job_id = await jobs.enqueue("build_graph", sim_id=sim.id)
    await s.commit()
    return sim.job_id


async def queue_environment(s: AsyncSession, sim: Simulation) -> str:
    if sim.status not in ("graph_ready", "ready", "completed", "failed", "cancelled"):
        raise Conflict("Build the graph first.")
    sim.status, sim.error = "preparing", None
    await s.commit()
    sim.job_id = await jobs.enqueue("prepare_environment", sim_id=sim.id)
    await s.commit()
    return sim.job_id


async def queue_run(s: AsyncSession, sim: Simulation, user_id: str | None = None) -> str:
    # Serialize the quota check and reservation in one process (including SQLite)
    # and lock the organisation row across PostgreSQL worker/API replicas.
    async with _start_locks[sim.org_id]:
        await s.refresh(sim)
        return await _queue_run(s, sim, user_id)


async def _queue_run(s: AsyncSession, sim: Simulation, user_id: str | None = None) -> str:
    if sim.status not in ("ready", "completed", "failed", "cancelled") or not (sim.config or {}).get("agents"):
        raise Conflict("Prepare the environment first.")
    org = (await s.execute(select(Organization).where(Organization.id == sim.org_id).with_for_update())).scalar_one()
    res = await resolve(s, sim.org_id)
    await check_start(s, org, sim.config, res.metered)
    for model in (Action, Post):
        await s.execute(delete(model).where(model.simulation_id == sim.id))
    await s.execute(delete(GraphNode).where(and_(GraphNode.simulation_id == sim.id, GraphNode.round >= 0)))
    await s.execute(delete(GraphEdge).where(and_(GraphEdge.simulation_id == sim.id, GraphEdge.round >= 0)))
    await s.execute(delete(Report).where(Report.simulation_id == sim.id))
    await s.execute(delete(SimEvent).where(and_(SimEvent.simulation_id == sim.id, SimEvent.type.notlike("graph.%"), SimEvent.type.notlike("env.%"))))
    sim.status, sim.error, sim.results, sim.progress, sim.report_status = "queued", None, {}, {"round": 0, "rounds": sim.config["time"]["rounds"]}, "none"
    audit.record(s, "simulation.start", org_id=sim.org_id, user_id=user_id, target=sim.id, meta={"credits_estimate": sim.credits_estimate})
    await s.commit()
    # graph.delta events from an earlier run stay in the log; clients replaying it drop that run's nodes here
    await bus.publish(sim.id, "graph.prune", {"min_round": 0})
    await bus.publish(sim.id, "simulation.queued", {"rounds": sim.config["time"]["rounds"]})
    sim.job_id = await jobs.enqueue("run_simulation", sim_id=sim.id)
    await s.commit()
    return sim.job_id


async def make_copy(s: AsyncSession, sim: Simulation, mode: str = "edit", changes: dict | None = None, user_id: str | None = None,
                    autopilot: bool = False) -> Simulation:
    """mode "edit": version B is an editable copy of A with `changes` applied; mode "rerun": same content and audience again,
    conditioned on the live context at the time it runs (trend re-simulation)."""
    from app.db.base import utcnow
    content = dict(sim.content or {})
    content.pop("card_b", None)
    if mode == "rerun":
        content["variant_b"] = (sim.content or {}).get("variant_b")
        name = f"{sim.name} · re-run {utcnow():%d %b}"
    else:
        keys = ("type", "text", "transcript", "description", "asset_id", "asset_ids", "poll_options")
        content["variant_b"] = {k: content.get(k) for k in keys} | {"title": f"{content.get('title') or ''} (edited)"} | (changes or {})
        content["b_kind"] = "version"
        name = f"{sim.name} · re-test"
    cfg = {"overrides": (sim.config or {}).get("overrides", {}), "autopilot": autopilot}
    for k in ("watch_id",):
        if (sim.config or {}).get(k):
            cfg[k] = sim.config[k]
    if mode == "rerun":
        cfg["rerun_of"] = sim.id
    new = Simulation(org_id=sim.org_id, project_id=sim.project_id, created_by=user_id or sim.created_by, name=name[:200], requirement=sim.requirement,
                     content=content, audience=sim.audience, publish_at=None, parent_id=sim.id, config=cfg)
    s.add(new)
    audit.record(s, "simulation.clone", org_id=sim.org_id, user_id=user_id, target=sim.id, meta={"mode": mode, "autopilot": autopilot})
    await s.commit()
    await s.refresh(new)
    return new
