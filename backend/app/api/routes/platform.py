"""Health, reference data, calibration and platform administration."""
from __future__ import annotations

import numpy as np
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, principal, superuser
from app.api.routes.workspace import _provider_out, _upsert_provider
from app.core.errors import NotFound
from app.core.metrics import render
from app.core.redis import get_redis
from app.db.session import get_session
from app.models import Organization, PerformanceReport, ProviderConfig, Simulation, SocialPost, User
from app.schemas.workspace import AdminOrgUpdate, ProviderIn
from app.services import audit, jobs
from app.services.content import formats
from app.services.datapool import REGISTRY
from app.services.llm import PRESETS
from app.services.population.regions import (
    AGE_BAND_LABELS,
    EDUCATION,
    INCOME_LABELS,
    INTEREST_LABELS,
    INTERESTS,
    MENA_CODES,
    PLATFORM_LABELS,
    PLATFORMS,
    PROFESSIONS,
    REGIONS,
    STANCES,
)
from app.services.quotas import PLANS, ledger

router = APIRouter()


@router.get("/healthz", tags=["ops"])
async def healthz():
    return {"status": "ok"}


@router.get("/readyz", tags=["ops"])
async def readyz(s: AsyncSession = Depends(get_session)):
    await s.execute(text("SELECT 1"))
    r = get_redis()
    if r is not None:
        await r.ping()
    return {"status": "ready", "redis": r is not None}


@router.get("/metrics", tags=["ops"], include_in_schema=False)
async def metrics():
    body, ctype = render()
    return Response(body, media_type=ctype)


@router.get("/reference", tags=["reference"])
async def reference():
    return {"regions": [{"code": r["code"], "name": r["name"], "short": r["short"], "city": r["city"], "mena": r["code"] in MENA_CODES,
                         "tz_offset": r["tz_offset"]} for r in REGIONS],
            "platforms": [{"key": p, "label": PLATFORM_LABELS[p]} for p in PLATFORMS], "stances": STANCES, "age_bands": AGE_BAND_LABELS,
            "education": EDUCATION, "interests": [{"key": k, "label": INTEREST_LABELS[k]} for k in INTERESTS], "presets": PRESETS,
            "professions": PROFESSIONS, "incomes": INCOME_LABELS, "formats": formats.public(),
            "plans": PLANS, "connectors": [{"key": k, "name": c.spec.name, "category": c.spec.category} for k, c in REGISTRY.items()]}


def _spearman(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    if x.size < 3:
        return None
    def ranks(values):
        _, inv, count = np.unique(values, return_inverse=True, return_counts=True)
        ends = np.cumsum(count)
        return ((ends - count + ends - 1) / 2)[inv]
    rx, ry = ranks(x), ranks(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return round(float(np.corrcoef(rx, ry)[0, 1]), 3)


@router.get("/calibration", tags=["calibration"])
async def calibration(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(PerformanceReport, Simulation, SocialPost).join(Simulation, Simulation.id == PerformanceReport.simulation_id)
                            .outerjoin(SocialPost, SocialPost.id == PerformanceReport.social_post_id)
                            .where(PerformanceReport.org_id == p.org_id, Simulation.org_id == p.org_id).order_by(PerformanceReport.created_at))).all()
    latest = {}
    for pr, sim, post in rows:
        key = (pr.simulation_id, pr.platform, pr.variant)
        if key not in latest or post is not None or latest[key][2] is None:
            latest[key] = (pr, sim, post)
    data = []
    for pr, sim, post in latest.values():
        r = sim.results or {}
        if not r.get("score"):
            continue
        predicted_score = r.get("ab", {}).get(pr.variant.lower(), {}).get("score", r["score"]["mean"])
        if post is not None:
            predicted_score = post.predicted_score
        data.append({"simulation_id": sim.id, "name": sim.name, "platform": pr.platform, "variant": pr.variant,
                     "source": "automatic" if pr.social_post_id else "manual", "predicted_score": predicted_score,
                     "predicted_viral": r.get("viral", {}).get("score") if pr.variant == "A" else None,
                     "predicted_share": r.get("viral", {}).get("raw", {}).get("mean_share_intent") if pr.variant == "A" else None,
                     "views": pr.views, "engagement_rate": pr.engagement_rate, "retention": pr.retention, "reported_at": pr.created_at})
    corr = {}
    for pred in ("predicted_score", "predicted_viral", "predicted_share"):
        for real in ("engagement_rate", "views", "retention"):
            pairs = [(d[pred], d[real]) for d in data if d[real] is not None and d[pred] is not None]
            if len(pairs) >= 3:
                corr[f"{pred}~{real}"] = {"rho": _spearman(*zip(*pairs)), "n": len(pairs)}
    return {"rows": data, "n": len(data), "correlations": corr}


# ---- platform administration --------------------------------------------------------------------------------
@router.get("/admin/overview", tags=["admin"])
async def overview(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    orgs = (await s.execute(select(func.count()).select_from(Organization))).scalar()
    users = (await s.execute(select(func.count()).select_from(User))).scalar()
    by_status = dict((await s.execute(select(Simulation.status, func.count()).group_by(Simulation.status))).all())
    return {"orgs": orgs, "users": users, "simulations": by_status, "queue": await jobs.queue_depth()}


@router.get("/admin/orgs", tags=["admin"])
async def admin_orgs(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Organization).order_by(desc(Organization.created_at)).limit(500))).scalars().all()
    sims = dict((await s.execute(select(Simulation.org_id, func.count()).group_by(Simulation.org_id))).all())
    return [{"id": o.id, "name": o.name, "plan": o.plan, "credits_balance": o.credits_balance, "max_concurrent": o.max_concurrent,
             "simulations": sims.get(o.id, 0), "created_at": o.created_at} for o in rows]


@router.patch("/admin/orgs/{org_id}", tags=["admin"])
async def admin_update_org(org_id: str, body: AdminOrgUpdate, user: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    o = await s.get(Organization, org_id)
    if not o:
        raise NotFound("Organisation not found.")
    if body.plan:
        o.plan = body.plan
        o.max_concurrent = PLANS[body.plan]["max_concurrent"]
    if body.max_concurrent:
        o.max_concurrent = body.max_concurrent
    if body.credits_delta:
        await ledger(s, o.id, body.credits_delta, "admin_adjust", user.id)
    audit.record(s, "admin.org_update", org_id=o.id, user_id=user.id, meta=body.model_dump(exclude_none=True))
    await s.commit()
    return {"ok": True, "credits_balance": o.credits_balance, "plan": o.plan}


@router.get("/admin/provider", tags=["admin"])
async def platform_provider(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    c = (await s.execute(select(ProviderConfig).where(and_(ProviderConfig.org_id.is_(None), ProviderConfig.is_default.is_(True))))).scalars().first()
    return {"config": _provider_out(c) if c else None, "presets": PRESETS}


@router.put("/admin/provider", tags=["admin"])
async def save_platform_provider(body: ProviderIn, user: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    c = await _upsert_provider(s, None, body)
    audit.record(s, "admin.platform_provider", user_id=user.id, meta={"preset": body.preset})
    await s.commit()
    return _provider_out(c)
