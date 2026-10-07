"""Creator benchmarking, version history, review workflow, annotations, the debate transcript, audience templates
(the persona library) and workspace branding."""
from __future__ import annotations

import copy
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.api.deps import Principal, get_sim, principal, role
from app.core.errors import Forbidden, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Annotation, AudienceTemplate, Organization, Post, SimAgent, Simulation, User
from app.schemas.simulation import AudienceIn
from app.services import audit
from app.services.population.regions import INTEREST_LABELS

router = APIRouter(tags=["collaboration"])
MIN_BENCHMARK = 5


# ---- creator benchmarking (anonymous, cross-workspace) --------------------------------------------------------------
@router.get("/simulations/{sim_id}/benchmark")
async def benchmark(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if sim.score is None:
        return {"available": False, "reason": "The simulation has not completed yet."}

    async def scores(where) -> list[float]:
        return [x for (x,) in (await s.execute(select(Simulation.score).where(and_(Simulation.score.is_not(None), Simulation.id != sim.id, where)))).all()]

    pool, scope = [], ""
    if sim.niche:
        pool = await scores(Simulation.niche == sim.niche)
        scope = INTEREST_LABELS.get(sim.niche, sim.niche)
    if len(pool) < MIN_BENCHMARK:
        pool, scope = await scores(Simulation.score.is_not(None)), "all content"
    if len(pool) < MIN_BENCHMARK:
        return {"available": False, "n": len(pool), "reason": f"Benchmarks appear once at least {MIN_BENCHMARK} other simulations have completed."}
    pool.sort()
    below = sum(1 for x in pool if x < sim.score)
    top10 = pool[int(0.9 * (len(pool) - 1))]
    mine = (await s.execute(select(func.avg(Simulation.score), func.count()).where(and_(Simulation.org_id == p.org_id, Simulation.score.is_not(None))))).one()
    return {"available": True, "scope": scope, "n": len(pool), "percentile": round(100 * below / len(pool)),
            "median": round(pool[len(pool) // 2], 2), "top10_threshold": round(top10, 2), "gap_to_top10": round(max(0.0, top10 - sim.score), 2),
            "workspace_average": round(float(mine[0]), 2) if mine[0] is not None else None, "workspace_runs": int(mine[1]),
            "method": "Projected opinion of this run against every other completed run on Kruvim in the same niche (anonymous; "
                      "only aggregate figures are returned)."}


# ---- version history ----------------------------------------------------------------------------------------------
@router.get("/simulations/{sim_id}/versions")
async def versions(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    root = sim
    for _ in range(50):                                       # walk up to the original
        if not root.parent_id:
            break
        parent = (await s.execute(select(Simulation).where(and_(Simulation.id == root.parent_id, Simulation.org_id == p.org_id)))).scalar_one_or_none()
        if not parent:
            break
        root = parent
    family, frontier = [root], [root.id]
    while frontier and len(family) < 200:
        kids = (await s.execute(select(Simulation).where(and_(Simulation.parent_id.in_(frontier), Simulation.org_id == p.org_id)))).scalars().all()
        family += kids
        frontier = [k.id for k in kids]
    family.sort(key=lambda x: x.created_at)
    return [{"id": x.id, "name": x.name, "parent_id": x.parent_id, "status": x.status, "score": x.score, "created_at": x.created_at,
             "title": (x.content or {}).get("title"), "current": x.id == sim.id} for x in family]


# ---- review workflow ----------------------------------------------------------------------------------------------
class ReviewIn(BaseModel):
    status: Literal["in_review", "approved", "changes_requested", "none"]
    note: str = Field(default="", max_length=2000)


@router.post("/simulations/{sim_id}/review")
async def review(sim_id: str, body: ReviewIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    if body.status in ("approved", "changes_requested"):
        p.require("admin")
    sim.review_status, sim.reviewed_by, sim.reviewed_at = body.status, p.user_id, utcnow()
    if body.note.strip():
        s.add(Annotation(simulation_id=sim.id, user_id=p.user_id, anchor="review", body=f"[{body.status.replace('_', ' ')}] {body.note.strip()}"))
    audit.record(s, f"simulation.review.{body.status}", org_id=p.org_id, user_id=p.user_id, target=sim.id)
    await s.commit()
    return {"review_status": sim.review_status, "reviewed_at": sim.reviewed_at}


# ---- annotations --------------------------------------------------------------------------------------------------
class AnnotationIn(BaseModel):
    anchor: str = Field(default="general", max_length=64, pattern=r"^(general|review|segment:\d+|post:\d+|section:\d+)$")
    body: str = Field(min_length=1, max_length=4000)


class AnnotationPatch(BaseModel):
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    resolved: bool | None = None


def _ann(a: Annotation, names: dict) -> dict:
    return {"id": a.id, "anchor": a.anchor, "body": a.body, "resolved": a.resolved, "created_at": a.created_at,
            "user_id": a.user_id, "author": names.get(a.user_id, "Former member")}


@router.get("/simulations/{sim_id}/annotations")
async def list_annotations(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(Annotation).where(Annotation.simulation_id == sim_id).order_by(Annotation.created_at))).scalars().all()
    ids = {a.user_id for a in rows if a.user_id}
    names = {u.id: u.name or u.email for u in (await s.execute(select(User).where(User.id.in_(ids)))).scalars()} if ids else {}
    return [_ann(a, names) for a in rows]


@router.post("/simulations/{sim_id}/annotations")
async def add_annotation(sim_id: str, body: AnnotationIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    a = Annotation(simulation_id=sim_id, user_id=p.user_id, anchor=body.anchor, body=body.body.strip())
    s.add(a)
    await s.commit()
    return _ann(a, {p.user_id: (p.user.name or p.user.email) if p.user else "API key"})


@router.patch("/annotations/{ann_id}")
async def edit_annotation(ann_id: str, body: AnnotationPatch, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    a = await _own_annotation(s, p, ann_id)
    if body.body is not None:
        if a.user_id != p.user_id:
            raise Forbidden("Only the author can edit a comment.")
        a.body = body.body.strip()
    if body.resolved is not None:
        a.resolved = body.resolved
    await s.commit()
    return {"ok": True}


@router.delete("/annotations/{ann_id}")
async def delete_annotation(ann_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    a = await _own_annotation(s, p, ann_id)
    if a.user_id != p.user_id:
        p.require("admin")
    await s.delete(a)
    await s.commit()
    return {"ok": True}


async def _own_annotation(s: AsyncSession, p: Principal, ann_id: str) -> Annotation:
    a = (await s.execute(select(Annotation).join(Simulation, Simulation.id == Annotation.simulation_id)
                         .where(and_(Annotation.id == ann_id, Simulation.org_id == p.org_id)))).scalar_one_or_none()
    if not a:
        raise NotFound("Comment not found.")
    return a


# ---- debate transcript --------------------------------------------------------------------------------------------
@router.get("/simulations/{sim_id}/transcript")
async def transcript(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session),
                     region: str | None = None, stance: str | None = None, sentiment: Literal["positive", "neutral", "negative"] | None = None,
                     platform: str | None = None, kind: Literal["voice", "stakeholder"] | None = None, q: str | None = Query(None, max_length=100),
                     offset: int = 0, limit: int = Query(100, le=500)):
    await get_sim(s, p, sim_id)
    agents = {a.ref: a for a in (await s.execute(select(SimAgent).where(SimAgent.simulation_id == sim_id))).scalars()}
    qry = select(Post).where(and_(Post.simulation_id == sim_id, Post.content != "", Post.kind.in_(["post", "comment", "quote"])))
    if platform:
        qry = qry.where(Post.platform == platform)
    if q:
        qry = qry.where(Post.content.ilike(f"%{q}%"))
    rows = (await s.execute(qry.order_by(Post.round, Post.id).limit(5000))).scalars().all()
    by_id = {x.id: x for x in rows}
    out = []
    for x in rows:
        a = agents.get(x.author_ref)
        if a is None and (region or stance or kind):
            continue
        if region and a.region != region:
            continue
        if stance and (a.persona or {}).get("stance") != stance:
            continue
        if kind and a.kind != kind:
            continue
        sent = "positive" if (x.sentiment or 0) > 0.15 else "negative" if (x.sentiment or 0) < -0.15 else "neutral"
        if sentiment and sent != sentiment:
            continue
        parent = by_id.get(x.parent_id) if x.parent_id else None
        out.append({"id": x.id, "round": x.round, "sim_time": x.sim_time, "platform": x.platform, "kind": x.kind, "content": x.content,
                    "sentiment": sent, "author": x.author_name, "author_ref": x.author_ref, "author_kind": a.kind if a else x.author_ref,
                    "region": a.region if a else None, "stance": (a.persona or {}).get("stance") if a else None,
                    "age": (a.persona or {}).get("age") if a else None, "stats": x.stats,
                    "reply_to": {"id": parent.id, "author": parent.author_name, "content": parent.content[:160]} if parent else None})
    return {"total": len(out), "items": out[offset: offset + limit]}


# ---- audience templates (persona library) --------------------------------------------------------------------------
class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)
    filters: AudienceIn
    source_citation: str = Field(default="", max_length=1000)
    shared: bool = False


def _tpl(t: AudienceTemplate, org_id: str) -> dict:
    return {"id": t.id, "name": t.name, "description": t.description, "filters": t.filters, "source_citation": t.source_citation,
            "shared": t.shared, "uses": t.uses, "accuracy": t.accuracy, "mine": t.org_id == org_id, "created_at": t.created_at}


@router.get("/audience-templates")
async def list_templates(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), scope: Literal["all", "mine", "community"] = "all"):
    cond = {"mine": AudienceTemplate.org_id == p.org_id, "community": AudienceTemplate.shared.is_(True),
            "all": or_(AudienceTemplate.org_id == p.org_id, AudienceTemplate.shared.is_(True))}[scope]
    rows = (await s.execute(select(AudienceTemplate).where(cond).order_by(AudienceTemplate.accuracy.desc().nulls_last(),
                                                                          AudienceTemplate.uses.desc()).limit(300))).scalars().all()
    return [_tpl(t, p.org_id) for t in rows]


@router.post("/audience-templates")
async def create_template(body: TemplateIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    t = AudienceTemplate(org_id=p.org_id, created_by=p.user_id, name=body.name, description=body.description,
                         filters=body.filters.model_dump(), source_citation=body.source_citation, shared=body.shared)
    s.add(t)
    audit.record(s, "audience_template.create", org_id=p.org_id, user_id=p.user_id, target=body.name)
    await s.commit()
    return _tpl(t, p.org_id)


@router.patch("/audience-templates/{tpl_id}")
async def update_template(tpl_id: str, body: TemplateIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    t = await _own_template(s, p, tpl_id)
    t.name, t.description, t.filters, t.source_citation, t.shared = body.name, body.description, body.filters.model_dump(), body.source_citation, body.shared
    await s.commit()
    return _tpl(t, p.org_id)


@router.delete("/audience-templates/{tpl_id}")
async def delete_template(tpl_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    t = await _own_template(s, p, tpl_id)
    await s.delete(t)
    await s.commit()
    return {"ok": True}


@router.post("/audience-templates/{tpl_id}/use")
async def use_template(tpl_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    t = (await s.execute(select(AudienceTemplate).where(and_(AudienceTemplate.id == tpl_id, or_(AudienceTemplate.org_id == p.org_id,
                                                                                                 AudienceTemplate.shared.is_(True)))))).scalar_one_or_none()
    if not t:
        raise NotFound("Template not found.")
    t.uses += 1
    await s.commit()
    return _tpl(t, p.org_id)


async def _own_template(s: AsyncSession, p: Principal, tpl_id: str) -> AudienceTemplate:
    t = (await s.execute(select(AudienceTemplate).where(and_(AudienceTemplate.id == tpl_id, AudienceTemplate.org_id == p.org_id)))).scalar_one_or_none()
    if not t:
        raise NotFound("Template not found in this workspace.")
    return t


# ---- branding (white-label) ---------------------------------------------------------------------------------------
class BrandingIn(BaseModel):
    product_name: str = Field(default="", max_length=60)
    accent: str = Field(default="", pattern=r"^(#[0-9a-fA-F]{6})?$")
    logo_url: str = Field(default="", max_length=500, pattern=r"^(https://\S+)?$")
    report_footer: str = Field(default="", max_length=300)


@router.get("/orgs/current/branding")
async def get_branding(p: Principal = Depends(principal)):
    return (p.org.settings or {}).get("branding") or {}


@router.put("/orgs/current/branding")
async def set_branding(body: BrandingIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    if p.org.plan not in ("business", "enterprise") and not p.is_superuser:
        raise Forbidden("Custom branding is available on the Business and Enterprise plans.")
    org = await s.get(Organization, p.org_id)
    st = copy.deepcopy(org.settings or {})
    st["branding"] = body.model_dump()
    org.settings = st
    flag_modified(org, "settings")
    audit.record(s, "org.branding", org_id=p.org_id, user_id=p.user_id)
    await s.commit()
    return st["branding"]
