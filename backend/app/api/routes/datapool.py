"""Data pool: connectors, live signals, world snapshots, social listening, barometer datasets, population versions."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, current_user, principal, role
from app.api.routes.sources import router as sources_router
from app.core.config import settings
from app.core.errors import AppError, Forbidden, NotFound
from app.db.session import get_session
from app.models import Connector, Dataset, DataSource, PopulationVersion, RegionSnapshot, Signal, User
from app.schemas.simulation import AudienceIn
from app.services import audit, jobs, storage
from app.services.datapool import REGISTRY, ensure_platform_connectors, listen, snapshots_at
from app.services.datapool.runner import env_secrets, secrets_of, set_secrets
from app.services.population import get_population
from app.services.population.calibrate import priors_from_summaries, sniff, summarize
from app.services.population.regions import REGION_CODES

router = APIRouter(prefix="/datapool", tags=["data pool"])

router.include_router(sources_router)


def _spec(key: str) -> dict:
    c = REGISTRY[key].spec
    return {"key": c.key, "name": c.name, "category": c.category, "description": c.description, "secrets": c.secrets,
            "supports_search": c.supports_search, "license_note": c.license_note, "docs_url": c.docs_url, "default_interval": c.interval_minutes}


@router.get("/connectors")
async def connectors(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await ensure_platform_connectors()
    rows = (await s.execute(select(Connector).where((Connector.org_id.is_(None)) | (Connector.org_id == p.org_id)))).scalars().all()
    plat = {r.key: r for r in rows if r.org_id is None}
    org = {r.key: r for r in rows if r.org_id == p.org_id}
    out = []
    for key in REGISTRY:
        r, o = plat.get(key), org.get(key)
        category = REGISTRY[key].spec.category
        max_age = {"weather": 1, "news": 3, "tone": 3, "attention": 6, "social": 6, "events": 24, "economy": 24}.get(category, 6)
        kind = {"news": "headline", "attention": "trend", "social": "social_trend", "events": "event"}.get(category, category)
        max_age = settings.signal_max_age_hours.get(kind, max_age)
        age = (datetime.now(UTC) - r.last_run_at).total_seconds() / 3600 if r and r.last_run_at else None
        sec = secrets_of(r)
        osec = secrets_of(o) if o else {}
        out.append({**_spec(key), "enabled": bool(r.enabled) if r else True, "interval_minutes": r.interval_minutes if r else 0,
                    "freshness": {"age_hours": round(age, 1) if age is not None else None, "max_age_hours": max_age,
                                  "stale": age is None or age > max_age or r.last_status != "ok"},
                    "last_run_at": r.last_run_at if r else None, "last_status": r.last_status if r else "never",
                    "last_error": r.last_error if r else None, "last_items": r.last_items if r else 0, "total_items": r.total_items if r else 0,
                    "credentials": {k: bool(sec.get(k)) for k in REGISTRY[key].spec.secrets},
                    "org_credentials": {k: bool(osec.get(k) and osec.get(k) != env_secrets().get(k)) for k in REGISTRY[key].spec.secrets}})
    return out


@router.patch("/connectors/{key}")
async def update_connector(key: str, body: dict, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session),
                           user: User = Depends(current_user)):
    """Superusers manage the platform connector (schedule, enabled, shared credentials). Org admins may store
    their own credentials for social listening (used only for their organisation's simulations)."""
    if key not in REGISTRY:
        raise NotFound("Unknown connector.")
    scope = body.get("scope", "platform" if user.is_superuser else "org")
    if scope == "platform" and not user.is_superuser:
        raise Forbidden("Only platform administrators can change shared connectors.")
    org_id = None if scope == "platform" else p.org_id
    row = (await s.execute(select(Connector).where(and_(Connector.key == key, Connector.org_id.is_(None) if org_id is None else Connector.org_id == org_id)))).scalar_one_or_none()
    if row is None:
        row = Connector(org_id=org_id, key=key, enabled=True, interval_minutes=REGISTRY[key].spec.interval_minutes if org_id is None else 0)
        s.add(row)
    if "enabled" in body:
        row.enabled = bool(body["enabled"])
    if "interval_minutes" in body and org_id is None:
        row.interval_minutes = max(0, min(1440, int(body["interval_minutes"])))
    if isinstance(body.get("config"), dict):
        row.config = {**(row.config or {}), **body["config"]}
    if isinstance(body.get("secrets"), dict):
        set_secrets(row, {k: v for k, v in body["secrets"].items() if k in REGISTRY[key].spec.secrets})
    audit.record(s, "connector.update", org_id=p.org_id, user_id=p.user_id, target=key, meta={"scope": scope})
    await s.commit()
    return {"ok": True}


@router.post("/connectors/{key}/run")
async def run_connector(key: str, p: Principal = Depends(role("admin")), user: User = Depends(current_user)):
    if key not in REGISTRY:
        raise NotFound("Unknown connector.")
    if not user.is_superuser:
        raise Forbidden("Only platform administrators can trigger shared connectors.")
    job = await jobs.enqueue("run_connector", key=key)
    return {"ok": True, "job_id": job}


@router.get("/signals")
async def signals(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), region: str | None = None,
                  kind: str | None = None, source: str | None = None, hours: int = 24, limit: int = 200):
    since = datetime.now(UTC) - timedelta(hours=max(1, min(hours, 24 * 30)))
    visible = (Signal.org_id.is_(None)) | (Signal.org_id == p.org_id)
    q = select(Signal).where(visible, Signal.fetched_at >= since)
    if region:
        q = q.where(Signal.region.in_([region, "*"]))
    if kind:
        q = q.where(Signal.kind == kind)
    if source:
        q = q.where(Signal.source == source)
    rows = (await s.execute(q.order_by(desc(Signal.fetched_at)).limit(min(limit, 1000)))).scalars().all()
    return [{"id": x.id, "source": x.source, "kind": x.kind, "region": x.region, "title": x.title, "value": x.value, "url": x.url,
             "lang": x.lang, "observed_at": x.observed_at, "fetched_at": x.fetched_at, "payload": x.payload} for x in rows]


@router.get("/stats")
async def pool_stats(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    since = datetime.now(UTC) - timedelta(hours=24)
    visible = (Signal.org_id.is_(None)) | (Signal.org_id == p.org_id)
    by_source = (await s.execute(select(Signal.source, func.count()).where(visible, Signal.fetched_at >= since).group_by(Signal.source))).all()
    by_kind = (await s.execute(select(Signal.kind, func.count()).where(visible, Signal.fetched_at >= since).group_by(Signal.kind))).all()
    total = (await s.execute(select(func.count()).select_from(Signal).where(visible))).scalar()
    snaps = (await s.execute(select(func.count(), func.min(RegionSnapshot.hour)).select_from(RegionSnapshot))).one()
    return {"signals_total": total, "last_24h": {"by_source": dict(by_source), "by_kind": dict(by_kind)},
            "archive": {"snapshots": snaps[0], "since": snaps[1]}}


@router.get("/world")
async def world(p: Principal = Depends(principal), regions: str = "", at: datetime | None = None,
                s: AsyncSession = Depends(get_session)):
    codes = [c for c in regions.split(",") if c in REGION_CODES] or REGION_CODES
    from app.services.llm import Usage, make_llm
    from app.services.providers import resolve
    from app.services.quotas import ensure_monthly_grant, ledger, reserve
    resolved = await resolve(s, p.org_id)
    usage = Usage()
    llm, held = make_llm(resolved.settings), 0
    reference = "headline-tone:" + uuid.uuid4().hex
    try:
        if resolved.metered and not llm.is_dry:
            await ensure_monthly_grant(s, p.org)
            maximum = 2 * len(codes)
            if p.org.credits_balance >= maximum:
                await reserve(s, p.org_id, maximum, "headline_tone_reserve", reference)
                held = maximum
                await s.commit()
            else:
                # Regional context remains usable when there are no model credits.
                await llm.aclose()
                llm = None
        return await snapshots_at(codes, at, llm, usage, org_id=p.org_id, with_briefs=False)
    finally:
        if held:
            await ledger(s, p.org_id, held - usage.calls, "headline_tone_refund", reference)
            await s.commit()
        if llm:
            await llm.aclose()


@router.post("/listen")
async def listen_route(body: dict, p: Principal = Depends(role("member"))):
    q = str(body.get("query") or "").strip()
    if len(q) < 2:
        raise AppError("Enter a topic to listen for.")
    regs = [c for c in body.get("regions") or [] if c in REGION_CODES] or ["AE"]
    return await listen(q.split()[:3], regs, p.org_id, per_source=8)


# ---- barometer datasets ----------------------------------------------------------------------------------
@router.get("/datasets")
async def datasets(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Dataset).where((Dataset.org_id == p.org_id) | (Dataset.org_id.is_(None))).order_by(desc(Dataset.created_at)))).scalars().all()
    return [{"id": d.id, "name": d.name, "source": d.source, "filename": d.filename, "rows": d.rows, "columns": d.columns, "preview": d.preview[:5],
             "registered_source_id": d.registered_source_id,
             "mapping": d.mapping, "summary": d.summary, "status": d.status, "error": d.error, "created_at": d.created_at, "scope": "platform" if d.org_id is None else "org"}
            for d in rows]


@router.post("/datasets")
async def upload_dataset(file: UploadFile = File(...), name: str = Form(""), source: str = Form("custom"),
                         registered_source_id: str = Form(""),
                         p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise AppError("File too large.", status=413)
    registered = None
    if registered_source_id:
        registered = await s.get(DataSource, registered_source_id)
        if not registered or registered.status in ("deprecated", "placeholder"):
            raise AppError("Choose a registered statistical source awaiting import or already active.")
    try:
        if registered:
            from app.services.sources.adapters import table
            columns, rows = table(data, file.filename or "data.csv")
            meta = {"columns": columns, "preview": [[r[c] for c in columns] for r in rows[:5]], "rows": len(rows)}
        else:
            meta = sniff(data)
    except Exception as exc:
        raise AppError(f"Could not read the table: {exc}", status=422)
    suffix = ".xlsx" if (file.filename or "").lower().endswith(".xlsx") else ".csv"
    key = f"{p.org_id}/datasets/{uuid.uuid4().hex}{suffix}"
    await storage.put(key, data)
    d = Dataset(org_id=p.org_id, name=name or file.filename or "dataset", source=source, filename=file.filename or "data.csv", storage_key=key,
                columns=meta["columns"], preview=meta["preview"], rows=meta["rows"], registered_source_id=registered_source_id or None)
    s.add(d)
    audit.record(s, "dataset.upload", org_id=p.org_id, user_id=p.user_id, target=d.name)
    await s.commit()
    return {"id": d.id, "columns": d.columns, "preview": d.preview, "rows": d.rows, "registered_source_id": d.registered_source_id}


@router.put("/datasets/{dataset_id}/mapping")
async def map_dataset(dataset_id: str, mapping: dict, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    d = (await s.execute(select(Dataset).where(and_(Dataset.id == dataset_id, Dataset.org_id == p.org_id)))).scalar_one_or_none()
    if not d:
        raise NotFound("Dataset not found.")
    if not d.registered_source_id and not mapping.get("country_col"):
        raise AppError("Choose the column that holds the country.")
    try:
        if d.registered_source_id:
            from app.services.sources.adapters import parse_table
            observations, missing = parse_table(await storage.get(d.storage_key), mapping, d.filename)
            summary = {"observations": len(observations), "missing_cells": missing, "preview": observations[:20],
                       "geographies": sorted({x["geography"] for x in observations}), "native_grain": True}
            # Dates must be JSON-safe in the stored preview.
            summary = json.loads(json.dumps(summary, default=str))
        else:
            summary = summarize(await storage.get(d.storage_key), mapping)
    except Exception as exc:
        d.status, d.error = "error", str(exc)[:500]
        await s.commit()
        raise AppError(f"Mapping failed: {exc}", status=422)
    d.mapping, d.summary, d.status, d.error = mapping, summary, "mapped", None
    await s.commit()
    return {"summary": summary}


@router.post("/datasets/{dataset_id}/apply")
async def apply_dataset(dataset_id: str, p: Principal = Depends(role("admin")), user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    if not user.is_superuser:
        raise Forbidden("Recalibrating the shared population requires a platform administrator.")
    d = (await s.execute(select(Dataset).where(Dataset.id == dataset_id,
         (Dataset.org_id == p.org_id) | Dataset.org_id.is_(None)))).scalar_one_or_none()
    if not d or d.status not in ("mapped", "applied"):
        raise AppError("Map the dataset's columns first.")
    if d.registered_source_id:
        from app.services.sources import eligible, store_observations
        from app.services.sources.adapters import parse_table
        registered = await s.get(DataSource, d.registered_source_id)
        if registered.status in ("deprecated", "placeholder"):
            raise AppError("This registered source is not available for publication.")
        observations, missing = parse_table(await storage.get(d.storage_key), d.mapping, d.filename)
        count = await store_observations(s, registered, observations, "asset:" + d.id)
        d.status = "applied"
        audit.record(s, "source.import", org_id=p.org_id, user_id=p.user_id, target=registered.id,
                     meta={"dataset_id": d.id, "observations": count, "missing_cells": missing})
        await s.commit()
        return {"observations": count, "missing_cells": missing, "production_eligible": eligible(registered)}
    applied = (await s.execute(select(Dataset).where(Dataset.status == "applied", Dataset.registered_source_id.is_(None),
               (Dataset.org_id == p.org_id) | Dataset.org_id.is_(None)))).scalars().all()
    priors = priors_from_summaries([x.summary for x in applied if x.id != d.id] + [d.summary])
    if not priors:
        raise AppError("No region in this dataset has at least 100 respondents.")
    v = PopulationVersion(label=f"Calibrated with {d.name}", size=settings.population_size, seed=settings.population_seed, priors=priors,
                          dataset_ids=[x.id for x in applied if x.id != d.id] + [d.id], status="pending")
    s.add(v)
    d.status = "applied"
    audit.record(s, "population.calibrate", org_id=p.org_id, user_id=p.user_id, target=d.name)
    await s.commit()
    await jobs.enqueue("build_population", version_id=v.id)
    return {"version_id": v.id, "regions": list(priors)}


# ---- population ---------------------------------------------------------------------------------------------
@router.get("/population")
async def population(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    from app.services.population.generator import stats
    pop = await get_population()
    v = (await s.execute(select(PopulationVersion).where(PopulationVersion.is_active.is_(True)))).scalar_one_or_none()
    st = v.stats if v and v.stats else stats(pop)
    versions = (await s.execute(select(PopulationVersion).order_by(desc(PopulationVersion.created_at)).limit(20))).scalars().all()
    return {"active": {"id": v.id if v else "base", "label": v.label if v else "Base priors", "priors": v.priors if v else {}}, "stats": st,
            "versions": [{"id": x.id, "label": x.label, "status": x.status, "is_active": x.is_active, "created_at": x.created_at,
                          "regions": list((x.priors or {}).keys()), "error": x.error} for x in versions]}


@router.post("/population/count")
async def audience_count(body: AudienceIn, p: Principal = Depends(principal)):
    import numpy as np
    pop = await get_population()
    m = pop.mask(body.model_dump())
    idx = np.flatnonzero(m)
    by_region = np.bincount(pop.region[idx].astype(np.int64), minlength=len(REGION_CODES)) if idx.size else np.zeros(len(REGION_CODES), int)
    return {"n": int(idx.size), "share": round(float(idx.size / pop.n), 5), "regions": {REGION_CODES[k]: int(v) for k, v in enumerate(by_region) if v}}


@router.get("/population/agents/{idx}")
async def population_agent(idx: int, p: Principal = Depends(principal)):
    pop = await get_population()
    if not 0 <= idx < pop.n:
        raise NotFound("No such agent.")
    return pop.persona(idx)


__all__ = ["router", "json"]
