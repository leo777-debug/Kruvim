"""Competitor monitoring, alerts, batch testing, autopilot runs and recurring trend re-runs."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_project, get_sim, principal, role
from app.api.routes.projects import sim_summary
from app.core.errors import AppError, Conflict, Forbidden, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Alert, Simulation, Watch
from app.schemas.simulation import AudienceIn
from app.services import audit, lifecycle, monitoring
from app.services.content.formats import FORMATS

router = APIRouter(tags=["monitoring"])


# ---- watches ----------------------------------------------------------------------------------------------------
class WatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    feed_url: str = Field(min_length=8, max_length=1000)
    project_id: str
    format: str = "social_post"
    platform: str = "x"
    audience: AudienceIn = Field(default_factory=AudienceIn)
    threshold: float = Field(default=0.5, ge=0, le=5)
    active: bool = True


def _watch(w: Watch, runs: int = 0) -> dict:
    return {"id": w.id, "name": w.name, "feed_url": w.feed_url, "project_id": w.project_id, "format": w.format, "platform": w.platform,
            "audience": w.audience, "threshold": w.threshold, "active": w.active, "last_checked_at": w.last_checked_at,
            "last_error": w.last_error, "created_at": w.created_at, "runs": runs}


@router.get("/watches")
async def list_watches(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Watch).where(Watch.org_id == p.org_id).order_by(Watch.created_at))).scalars().all()
    limit = monitoring.watch_limit(p.org, False)
    sims = (await s.execute(select(Simulation.config).where(Simulation.org_id == p.org_id))).all()
    counts: dict[str, int] = {}
    for (cfg,) in sims:
        wid = (cfg or {}).get("watch_id")
        if wid:
            counts[wid] = counts.get(wid, 0) + 1
    return {"limit": limit, "plan": p.org.plan, "admin_override": p.is_superuser, "watches": [_watch(w, counts.get(w.id, 0)) for w in rows]}


async def _validate(s: AsyncSession, p: Principal, body: WatchIn) -> None:
    await get_project(s, p, body.project_id)
    monitoring.check_public_url(body.feed_url)
    if body.format not in FORMATS or FORMATS[body.format]["type"] != "text":
        raise AppError("Monitored posts are tested as text: choose a text or document format.")


@router.post("/watches")
async def create_watch(body: WatchIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    limit = monitoring.watch_limit(p.org, p.is_superuser)
    have = (await s.execute(select(func.count()).select_from(Watch).where(Watch.org_id == p.org_id))).scalar()
    if have >= limit:
        raise Forbidden("Competitor monitoring is available on the Pro (1 feed), Business (5) and Enterprise (50) plans." if limit == 0
                        else f"Your plan allows {limit} monitored feed{'s' if limit != 1 else ''}.")
    await _validate(s, p, body)
    w = Watch(org_id=p.org_id, created_by=p.user_id, **{**body.model_dump(), "audience": body.audience.model_dump()})
    s.add(w)
    audit.record(s, "watch.create", org_id=p.org_id, user_id=p.user_id, target=body.name)
    await s.commit()
    return _watch(w)


@router.patch("/watches/{watch_id}")
async def update_watch(watch_id: str, body: WatchIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    w = await _own(s, p, watch_id)
    await _validate(s, p, body)
    for k, v in {**body.model_dump(), "audience": body.audience.model_dump()}.items():
        setattr(w, k, v)
    await s.commit()
    return _watch(w)


@router.delete("/watches/{watch_id}")
async def delete_watch(watch_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    w = await _own(s, p, watch_id)
    await s.delete(w)
    audit.record(s, "watch.delete", org_id=p.org_id, user_id=p.user_id, target=w.name)
    await s.commit()
    return {"ok": True}


@router.post("/watches/{watch_id}/check")
async def check_now(watch_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await _own(s, p, watch_id)
    return await monitoring.check_watch(watch_id)


@router.get("/watches/{watch_id}/runs")
async def watch_runs(watch_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await _own(s, p, watch_id)
    rows = (await s.execute(select(Simulation).where(Simulation.org_id == p.org_id).order_by(desc(Simulation.created_at)).limit(500))).scalars().all()
    return [sim_summary(x) | {"source_url": (x.content or {}).get("source_url")} for x in rows if (x.config or {}).get("watch_id") == watch_id][:100]


async def _own(s: AsyncSession, p: Principal, watch_id: str) -> Watch:
    w = (await s.execute(select(Watch).where(and_(Watch.id == watch_id, Watch.org_id == p.org_id)))).scalar_one_or_none()
    if not w:
        raise NotFound("Monitored feed not found.")
    return w


# ---- alerts -----------------------------------------------------------------------------------------------------
@router.get("/alerts")
async def list_alerts(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), unread: bool = False, limit: int = 50):
    q = select(Alert).where(Alert.org_id == p.org_id)
    if unread:
        q = q.where(Alert.read.is_(False))
    rows = (await s.execute(q.order_by(desc(Alert.created_at)).limit(min(limit, 200)))).scalars().all()
    n = (await s.execute(select(func.count()).select_from(Alert).where(and_(Alert.org_id == p.org_id, Alert.read.is_(False))))).scalar()
    return {"unread": n, "items": [{"id": a.id, "kind": a.kind, "title": a.title, "body": a.body, "read": a.read, "created_at": a.created_at,
                                    "simulation_id": a.simulation_id, "watch_id": a.watch_id} for a in rows]}


@router.post("/alerts/read")
async def mark_read(ids: list[str] | None = Body(default=None, embed=True), p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    q = update(Alert).where(Alert.org_id == p.org_id)
    if ids:
        q = q.where(Alert.id.in_(ids))
    await s.execute(q.values(read=True))
    await s.commit()
    return {"ok": True}


# ---- autopilot, batch, recurring -----------------------------------------------------------------------------------
async def _autopilot(s: AsyncSession, sim: Simulation, user_id: str | None) -> str:
    """Turn on autopilot and start whichever step is next."""
    sim.config = {**(sim.config or {}), "autopilot": True}
    await s.commit()
    if sim.status in lifecycle.LOCKED:
        return "already running"
    if sim.status in ("ready",):
        await lifecycle.queue_run(s, sim, user_id)
        return "simulation queued"
    if sim.status == "graph_ready":
        await lifecycle.queue_environment(s, sim)
        return "environment queued"
    await lifecycle.queue_graph(s, sim)
    return "graph queued"


@router.post("/simulations/{sim_id}/autopilot")
async def autopilot(sim_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    return {"ok": True, "status": await _autopilot(s, sim, p.user_id)}


class BatchIn(BaseModel):
    simulation_ids: list[str] = Field(min_length=1, max_length=50)


@router.post("/projects/{project_id}/batch")
async def batch(project_id: str, body: BatchIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    """Batch testing: run several simulations end to end. Each still counts against plan concurrency and credits."""
    await get_project(s, p, project_id)
    out = []
    for sid in body.simulation_ids:
        sim = (await s.execute(select(Simulation).where(and_(Simulation.id == sid, Simulation.project_id == project_id, Simulation.org_id == p.org_id)))).scalar_one_or_none()
        if not sim:
            out.append({"id": sid, "ok": False, "error": "Not found in this project."})
            continue
        try:
            out.append({"id": sid, "ok": True, "status": await _autopilot(s, sim, p.user_id)})
        except (AppError, Conflict) as exc:
            out.append({"id": sid, "ok": False, "error": exc.message})
    audit.record(s, "simulation.batch", org_id=p.org_id, user_id=p.user_id, target=project_id, meta={"n": len(body.simulation_ids)})
    await s.commit()
    return {"results": out}


class ScheduleIn(BaseModel):
    every_days: int | None = Field(default=None, ge=1, le=90)


@router.put("/simulations/{sim_id}/rerun-schedule")
async def rerun_schedule(sim_id: str, body: ScheduleIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    """Recurring trend re-simulation: re-run the same content and audience against fresh live context every N days."""
    sim = await get_sim(s, p, sim_id)
    if body.every_days and sim.status != "completed":
        raise Conflict("Schedule re-runs once the simulation has completed.")
    sim.rerun_every_days = body.every_days
    sim.next_rerun_at = utcnow() + timedelta(days=body.every_days) if body.every_days else None
    await s.commit()
    return {"rerun_every_days": sim.rerun_every_days, "next_rerun_at": sim.next_rerun_at}
