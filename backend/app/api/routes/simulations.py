"""The five-step workflow: graph → environment → simulation → report → interaction."""
from __future__ import annotations

import asyncio
import copy
import json

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import Principal, get_project, get_sim, principal, role
from app.api.routes.projects import sim_summary
from app.core.errors import AppError, Conflict, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import (
    Action,
    Asset,
    ChatMessage,
    PerformanceReport,
    Post,
    Report,
    SimAgent,
    SimEvent,
    Simulation,
    Survey,
)
from app.schemas.simulation import (
    ChatIn,
    CloneIn,
    ConfigPatch,
    ControlIn,
    ExploreIn,
    SimulationCreate,
    SimulationUpdate,
    SurveyIn,
)
from app.schemas.workspace import PerformanceIn
from app.services import audit, jobs, knowledge, lifecycle, metering
from app.services.events import bus
from app.services.interaction import ask
from app.services.llm import Usage, make_llm
from app.services.providers import resolve
from app.services.quotas import estimate_credits
from app.services.report import chat as report_chat
from app.services.simulation import agent_detail, explore

router = APIRouter(tags=["simulations"])
LOCKED = ("building_graph", "preparing", "queued", "running", "paused")


def full(sim: Simulation) -> dict:
    out = sim_summary(sim)
    out.update({"requirement": sim.requirement, "content": sim.content, "audience": sim.audience, "publish_at": sim.publish_at,
                "ontology": sim.ontology, "card": sim.card, "config": sim.config, "usage": sim.usage, "seed": sim.seed,
                "credits_charged": sim.credits_charged, "started_at": sim.started_at, "finished_at": sim.finished_at})
    r = dict(sim.results or {})
    for k in ("models", "topic_vector", "topic_vectors"):
        r.pop(k, None)
    out["results"] = r
    return out


@router.get("/projects/{project_id}/simulations")
async def list_sims(project_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_project(s, p, project_id)
    rows = (await s.execute(select(Simulation).where(Simulation.project_id == project_id).order_by(desc(Simulation.created_at)))).scalars().all()
    return [sim_summary(x) for x in rows]


@router.get("/simulations")
async def recent_sims(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), limit: int = 50):
    rows = (await s.execute(select(Simulation).where(Simulation.org_id == p.org_id).order_by(desc(Simulation.created_at)).limit(min(limit, 200)))).scalars().all()
    return [sim_summary(x) for x in rows]


async def _check_assets(s: AsyncSession, p: Principal, project_id: str, content: dict):
    vb = content.get("variant_b") or {}
    ids = [content.get("asset_id"), vb.get("asset_id"), *content.get("asset_ids", []), *vb.get("asset_ids", []), *content.get("seed_asset_ids", [])]
    ids = [i for i in ids if i]
    if ids:
        n = (await s.execute(select(func.count()).select_from(Asset).where(and_(Asset.id.in_(ids), Asset.org_id == p.org_id,
                                                                                 Asset.project_id == project_id)))).scalar()
        if n != len(set(ids)):
            raise AppError("One of the referenced files does not belong to this project.")


@router.post("/projects/{project_id}/simulations")
async def create_sim(project_id: str, body: SimulationCreate, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await get_project(s, p, project_id)
    content = body.content.model_dump()
    await _check_assets(s, p, project_id, content)
    sim = Simulation(org_id=p.org_id, project_id=project_id, created_by=p.user_id, name=body.name, requirement=body.requirement,
                     content=content, audience=body.audience.model_dump(), publish_at=body.publish_at,
                     config={"overrides": body.overrides.model_dump()})
    s.add(sim)
    audit.record(s, "simulation.create", org_id=p.org_id, user_id=p.user_id, target=sim.name)
    await s.commit()
    return full(sim)


@router.get("/simulations/{sim_id}")
async def get_sim_route(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    return full(await get_sim(s, p, sim_id))


@router.patch("/simulations/{sim_id}")
async def update_sim(sim_id: str, body: SimulationUpdate, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.status in LOCKED:
        raise Conflict("This simulation is busy; wait for the current step to finish.")
    data = body.model_dump(exclude_unset=True)
    graph_dirty = False
    if "name" in data:
        sim.name = data["name"]
    if "requirement" in data:
        sim.requirement = data["requirement"]
        graph_dirty = True
    if "content" in data and data["content"] is not None:
        await _check_assets(s, p, sim.project_id, data["content"])
        sim.content = data["content"]
        graph_dirty = True
    if "audience" in data and data["audience"] is not None:
        sim.audience = data["audience"]
        graph_dirty = True
    if "publish_at" in data:
        sim.publish_at = data["publish_at"]
        graph_dirty = True
    if "overrides" in data and data["overrides"] is not None:
        sim.config = {**(sim.config or {}), "overrides": data["overrides"]}
        if sim.status in ("ready",):
            sim.status = "graph_ready"
    if graph_dirty and sim.status not in ("draft",):
        sim.status, sim.step = "draft", 1
    await s.commit()
    return full(sim)


@router.delete("/simulations/{sim_id}")
async def delete_sim(sim_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.status in ("queued", "running", "paused"):
        raise Conflict("Stop the simulation before deleting it.")
    await s.delete(sim)
    audit.record(s, "simulation.delete", org_id=p.org_id, user_id=p.user_id, target=sim.name)
    await s.commit()
    return {"ok": True}


@router.post("/simulations/{sim_id}/clone")
async def clone_sim(sim_id: str, body: CloneIn | None = None, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    """Re-test a simulation.
    mode "edit":  new draft whose version B is an editable copy of A, with `changes` (e.g. an applied suggestion) already in B.
    mode "rerun": the same content and audience again, conditioned on today's live context (trend re-simulation)."""
    body = body or CloneIn()
    sim = await get_sim(s, p, sim_id)
    new = await lifecycle.make_copy(s, sim, body.mode, body.changes, p.user_id, autopilot=body.build)
    if body.build:
        await lifecycle.queue_graph(s, new)
    return full(new)


# ---- Step 1 · graph ------------------------------------------------------------------------------------------
async def _start_graph(s: AsyncSession, sim: Simulation) -> str:
    return await lifecycle.queue_graph(s, sim)


@router.post("/simulations/{sim_id}/graph")
async def build_graph(sim_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    return {"ok": True, "job_id": await _start_graph(s, sim)}


@router.get("/simulations/{sim_id}/graph")
async def graph(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), round: int | None = Query(None)):
    await get_sim(s, p, sim_id)
    return await knowledge.snapshot(sim_id, round)


@router.get("/simulations/{sim_id}/graph/search")
async def graph_search(sim_id: str, q: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    return await knowledge.search(sim_id, q, 20)


# ---- Step 2 · environment ------------------------------------------------------------------------------------
@router.post("/simulations/{sim_id}/environment")
async def prepare_environment(sim_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    return {"ok": True, "job_id": await lifecycle.queue_environment(s, sim)}


@router.patch("/simulations/{sim_id}/config")
async def patch_config(sim_id: str, body: ConfigPatch, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.status != "ready":
        raise Conflict("The configuration can be edited once the environment is ready and before the run starts.")
    cfg = copy.deepcopy(sim.config or {})
    data = body.model_dump(exclude_none=True)
    if "platforms" in data:
        for pl, vals in data["platforms"].items():
            if pl in cfg.get("platforms", {}) and isinstance(vals, dict):
                for k, v in vals.items():
                    if k in ("recency_weight", "popularity_weight", "relevance_weight", "echo_chamber"):
                        cfg["platforms"][pl][k] = max(0.0, min(1.0, float(v)))
                    elif k == "enabled":
                        cfg["platforms"][pl][k] = bool(v)
    if "events" in data:
        ev = cfg.setdefault("events", {})
        if isinstance(data["events"].get("scheduled"), list):
            rounds = cfg["time"]["rounds"]
            ev["scheduled"] = [{"round": max(1, min(rounds, int(x.get("round", 1)))), "text": str(x.get("text", ""))[:300], "source": x.get("source", "user")}
                               for x in data["events"]["scheduled"] if isinstance(x, dict) and x.get("text")][:20]
        if "narrative" in data["events"]:
            ev["narrative"] = str(data["events"]["narrative"])[:1000]
        if isinstance(data["events"].get("hot_topics"), list):
            ev["hot_topics"] = [str(x)[:80] for x in data["events"]["hot_topics"]][:10]
    if "analysis_focus" in data:
        cfg["analysis_focus"] = data["analysis_focus"][:500]
    if "external_seed" in data:
        cfg["external_seed"] = [x for x in data["external_seed"] if isinstance(x, dict)][:24]
    cfg["credits"] = estimate_credits(cfg)
    sim.config = cfg
    flag_modified(sim, "config")
    sim.credits_estimate = cfg["credits"]["total"]
    await s.commit()
    return full(sim)


@router.get("/simulations/{sim_id}/agents")
async def agents(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim_id).order_by(SimAgent.kind.desc(), SimAgent.id))).scalars().all()
    return [{"ref": r.ref, "kind": r.kind, "name": r.name, "handle": r.handle, "region": r.region, "followers": r.followers,
             "persona": {k: r.persona.get(k) for k in ("age", "gender", "city", "origin", "stance", "profession", "language", "role", "description",
                                                       "platforms", "interests", "education", "income")},
             "config": r.config, "reaction": {k: (r.reaction or {}).get(k) for k in ("score", "quote", "primary_emotion")} if r.reaction else None,
             "opinion": (r.state or {}).get("opinion"), "actions": (r.state or {}).get("actions")} for r in rows]


# ---- Step 3 · run ---------------------------------------------------------------------------------------------
@router.post("/simulations/{sim_id}/start")
async def start(sim_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    return {"ok": True, "job_id": await lifecycle.queue_run(s, sim, p.user_id)}


@router.post("/simulations/{sim_id}/control")
async def control(sim_id: str, body: ControlIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.status not in ("queued", "running", "paused"):
        raise Conflict("The simulation is not running.")
    if body.cmd == "inject" and not (body.text or "").strip():
        raise AppError("Describe the event to inject.")
    await jobs.send_control(sim_id, body.model_dump(exclude_none=True))
    audit.record(s, f"simulation.{body.cmd}", org_id=p.org_id, user_id=p.user_id, target=sim_id, meta={"text": body.text})
    await s.commit()
    return {"ok": True}


@router.get("/simulations/{sim_id}/events")
async def events(sim_id: str, request: Request, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session),
                 after: int = 0, follow: bool = True):
    await get_sim(s, p, sim_id)
    last = request.headers.get("last-event-id")
    start_after = int(last) if last and last.isdigit() else after

    async def gen():
        async for msg in bus.stream(sim_id, start_after, follow=follow):
            if await request.is_disconnected():
                return
            if msg == "":
                yield ": keep-alive\n\n"
                continue
            seq = json.loads(msg)["seq"]
            yield f"id: {seq}\ndata: {msg}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/simulations/{sim_id}/posts")
async def posts(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), platform: str | None = None,
                after_id: int = 0, limit: int = 200, root: int | None = None):
    await get_sim(s, p, sim_id)
    q = select(Post).where(and_(Post.simulation_id == sim_id, Post.id > after_id))
    if platform:
        q = q.where(Post.platform == platform)
    if root is not None:
        q = q.where((Post.root_id == root) | (Post.id == root))
    rows = (await s.execute(q.order_by(Post.id).limit(min(limit, 1000)))).scalars().all()
    return [{"id": x.id, "platform": x.platform, "kind": x.kind, "author_ref": x.author_ref, "author": x.author_name, "parent_id": x.parent_id,
             "root_id": x.root_id, "content": x.content, "round": x.round, "sim_time": x.sim_time, "stats": x.stats, "sentiment": x.sentiment,
             "url": x.source_url} for x in rows]


@router.get("/simulations/{sim_id}/actions")
async def actions(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), after_id: int = 0, limit: int = 300):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(Action).where(and_(Action.simulation_id == sim_id, Action.id > after_id)).order_by(Action.id).limit(min(limit, 2000)))).scalars().all()
    return [{"id": a.id, "round": a.round, "sim_time": a.sim_time, "platform": a.platform, "actor_ref": a.actor_ref, "actor": a.actor_name,
             "action": a.action, "post_id": a.post_id, "target_post": a.target_post_id, "target_ref": a.target_ref, "content": a.content, "meta": a.meta}
            for a in rows]


# ---- Step 4 · report ----------------------------------------------------------------------------------------
@router.get("/simulations/{sim_id}/report")
async def get_report(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    r = (await s.execute(select(Report).where(Report.simulation_id == sim_id).order_by(desc(Report.created_at)).limit(1))).scalar_one_or_none()
    if not r:
        return None
    logs = (await s.execute(select(SimEvent).where(and_(SimEvent.simulation_id == sim_id, SimEvent.type == "report.log")).order_by(SimEvent.seq))).scalars().all()
    return {"id": r.id, "status": r.status, "title": r.title, "summary": r.summary, "outline": r.outline, "sections": r.sections,
            "markdown": r.markdown, "model": r.model, "error": r.error, "created_at": r.created_at, "log": [x.payload for x in logs]}


@router.post("/simulations/{sim_id}/report")
async def regenerate_report(sim_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.status != "completed":
        raise Conflict("Run the simulation first.")
    if sim.report_status in ("queued", "running"):
        raise Conflict("A report is already being written.")
    sim.report_status = "queued"
    await s.commit()
    await jobs.enqueue("generate_report", sim_id=sim_id)
    return {"ok": True}


@router.post("/simulations/{sim_id}/report/chat")
async def chat_report(sim_id: str, body: ChatIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    rep = (await s.execute(select(Report).where(and_(Report.simulation_id == sim_id, Report.status == "done")).order_by(desc(Report.created_at)))).scalars().first()
    if not rep:
        raise Conflict("The report is not ready yet.")
    hist = [{"role": m.role, "content": m.content} for m in (await s.execute(select(ChatMessage).where(and_(
        ChatMessage.simulation_id == sim_id, ChatMessage.target == "report")).order_by(ChatMessage.id))).scalars()]
    res = await resolve(s, p.org_id)
    llm = make_llm(res.settings)
    usage = Usage()
    try:
        out = await asyncio.wait_for(report_chat(sim, rep.markdown, hist, body.message, llm, usage), timeout=240)
    finally:
        await llm.aclose()
    s.add_all([ChatMessage(simulation_id=sim_id, target="report", role="user", content=body.message, user_id=p.user_id),
               ChatMessage(simulation_id=sim_id, target="report", role="assistant", content=out["answer"], meta={"tools": out["tools"]})])
    await s.commit()
    await metering.record(p.org_id, sim_id, "chat", usage, res)
    return {**out, "history": hist + [{"role": "user", "content": body.message}, {"role": "assistant", "content": out["answer"]}]}


@router.get("/simulations/{sim_id}/report/chat")
async def report_chat_history(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(ChatMessage).where(and_(ChatMessage.simulation_id == sim_id, ChatMessage.target == "report")).order_by(ChatMessage.id))).scalars().all()
    return [{"role": m.role, "content": m.content, "meta": m.meta, "at": m.created_at} for m in rows]


# ---- Step 5 · interaction --------------------------------------------------------------------------------------
@router.get("/simulations/{sim_id}/agents/{ref}")
async def agent(sim_id: str, ref: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    d = await agent_detail(sim, ref)
    if not d:
        raise NotFound("Agent not found.")
    return d


@router.post("/simulations/{sim_id}/agents/{ref}/chat")
async def chat_agent(sim_id: str, ref: str, body: ChatIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if not sim.card:
        raise Conflict("This simulation has no analysed content yet.")
    d = await agent_detail(sim, ref)
    if not d:
        raise NotFound("Agent not found.")
    res = await resolve(s, p.org_id)
    llm = make_llm(res.settings)
    usage = Usage()
    try:
        reply = await asyncio.wait_for(ask(d, sim.card, (sim.content or {}).get("platform"), d.get("chat", []), body.message, llm, usage), timeout=120)
    finally:
        await llm.aclose()
    s.add_all([ChatMessage(simulation_id=sim_id, target=ref, role="user", content=body.message, user_id=p.user_id),
               ChatMessage(simulation_id=sim_id, target=ref, role="assistant", content=reply)])
    await s.commit()
    await metering.record(p.org_id, sim_id, "chat", usage, res)
    return {"reply": reply, "chat": d.get("chat", []) + [{"role": "user", "content": body.message}, {"role": "assistant", "content": reply}]}


@router.post("/simulations/{sim_id}/explore")
async def explore_route(sim_id: str, body: ExploreIn, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    out = await explore(sim, body.model_dump(exclude_none=True))
    if out is None:
        raise Conflict("Results are not ready yet.")
    return out


@router.post("/simulations/{sim_id}/surveys")
async def create_survey(sim_id: str, body: SurveyIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.status != "completed":
        raise Conflict("Run the simulation first.")
    sv = Survey(simulation_id=sim_id, question=body.question, filters=body.model_dump(exclude={"question"}, exclude_none=True))
    s.add(sv)
    await s.commit()
    await jobs.enqueue("run_survey", survey_id=sv.id)
    return {"id": sv.id, "status": sv.status}


@router.get("/simulations/{sim_id}/surveys")
async def list_surveys(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(Survey).where(Survey.simulation_id == sim_id).order_by(desc(Survey.created_at)))).scalars().all()
    out = []
    for x in rows:
        try:
            summ = json.loads(x.summary) if x.summary and x.summary.startswith("{") else {"takeaway": x.summary}
        except ValueError:
            summ = {"takeaway": x.summary}
        out.append({"id": x.id, "question": x.question, "filters": x.filters, "status": x.status, "answers": x.answers, "summary": summ,
                    "created_at": x.created_at})
    return out


# ---- calibration ------------------------------------------------------------------------------------------------
@router.post("/simulations/{sim_id}/performance")
async def add_performance(sim_id: str, body: PerformanceIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    d = body.model_dump()
    if d["engagement_rate"] is None and d["views"]:
        acts = sum(x or 0 for x in (d["likes"], d["shares"], d["comments"]))
        d["engagement_rate"] = round(100 * acts / d["views"], 3) if acts else None
    s.add(PerformanceReport(simulation_id=sim.id, org_id=p.org_id, reported_by=p.user_id, **d))
    await s.commit()
    rows = (await s.execute(select(PerformanceReport).where(PerformanceReport.simulation_id == sim.id).order_by(PerformanceReport.created_at))).scalars().all()
    return [{"platform": r.platform, "views": r.views, "engagement_rate": r.engagement_rate, "retention": r.retention, "at": r.created_at} for r in rows]


@router.get("/simulations/{sim_id}/performance")
async def list_performance(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(PerformanceReport).where(PerformanceReport.simulation_id == sim_id).order_by(PerformanceReport.created_at))).scalars().all()
    return [{"platform": r.platform, "views": r.views, "likes": r.likes, "shares": r.shares, "comments": r.comments,
             "engagement_rate": r.engagement_rate, "retention": r.retention, "notes": r.notes, "at": r.created_at} for r in rows]


@router.get("/simulations/{sim_id}/export")
async def export(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    rep = (await s.execute(select(Report).where(Report.simulation_id == sim_id).order_by(desc(Report.created_at)))).scalars().first()
    body = {"exported_at": utcnow().isoformat(), "simulation": full(sim), "report_markdown": rep.markdown if rep else None}
    return StreamingResponse(iter([json.dumps(body, default=str, ensure_ascii=False, indent=1)]), media_type="application/json",
                             headers={"Content-Disposition": f'attachment; filename="kruvim-{sim_id}.json"'})
