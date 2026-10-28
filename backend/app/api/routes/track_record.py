"""Forecasts, the workspace track record, the public scoreboard (off until enabled) and the public hash ledger."""
from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, client_ip, get_sim, principal, role
from app.core.config import settings
from app.core.errors import AppError, Conflict, NotFound
from app.core.ratelimit import hit
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Forecast, LedgerEntry
from app.services import audit
from app.services import track_record as tr

router = APIRouter(tags=["track record"])
Domain = Literal["launch", "statistics", "debate", "campaign", "other"]


class ForecastIn(BaseModel):
    question: str = Field(min_length=8, max_length=400)
    domain: Domain = "other"
    country: str = Field(default="GLOBAL", pattern=r"^(GLOBAL|[A-Z]{2}(-[A-Z0-9]{1,3})?)$")
    kind: Literal["numeric", "binary"] = "numeric"
    metric: Literal["score", "positive_share"] = "score"
    threshold: float | None = None
    resolution_criteria: str = Field(min_length=20, max_length=4000)
    resolves_on: date
    baseline_value: float
    baseline_method: str = Field(min_length=3, max_length=300)
    model_knowledge_cutoff: date | None = None
    simulation_id: str | None = None
    public: bool = False

    @model_validator(mode="after")
    def _consistent(self):
        low, high, label = tr.METRICS[self.metric]
        if self.kind == "binary":
            if self.metric != "score":
                raise ValueError("Yes/no forecasts use the reaction score, which carries an uncertainty interval.")
            if self.threshold is None or not low < self.threshold < high:
                raise ValueError(f"Set the threshold the {label} must reach, between {low:g} and {high:g}.")
            if not 0 < self.baseline_value < 1:
                raise ValueError("For a yes/no forecast the baseline is a probability between 0 and 1 (for example the base rate).")
        elif not low <= self.baseline_value <= high:
            raise ValueError(f"The baseline must be a {label} between {low:g} and {high:g}.")
        return self


class OutcomeIn(BaseModel):
    value: float
    evidence_url: str = Field(pattern=r"^https?://\S+$", max_length=1000)
    note: str = Field(default="", max_length=1000)


class VoidIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)


async def own(s: AsyncSession, org_id: str, forecast_id: str) -> Forecast:
    f = (await s.execute(select(Forecast).where(and_(Forecast.id == forecast_id, Forecast.org_id == org_id)))).scalar_one_or_none()
    if not f:
        raise NotFound("Forecast not found.")
    return f


def out(f: Forecast) -> dict:
    return {**tr.record_of_forecast(f), "resolution_criteria": f.resolution_criteria, "model_knowledge_cutoff": f.model_knowledge_cutoff,
            "simulation_id": f.simulation_id, "outcome_detail": f.outcome, "created_at": f.created_at, "resolved_at": f.resolved_at}


# ---- workspace -------------------------------------------------------------------------------------------------------
@router.get("/track-record")
async def workspace_record(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    records = await tr.workspace_records(s, p.org_id)
    return {"summary": tr.summarise(records), "records": records, "public_enabled": settings.public_track_record}


@router.post("/forecasts")
async def create(body: ForecastIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    f = Forecast(org_id=p.org_id, created_by=p.user_id, status="draft", prediction={}, outcome={}, **body.model_dump())
    if f.simulation_id:
        await get_sim(s, p, f.simulation_id)
    s.add(f)
    audit.record(s, "forecast.create", org_id=p.org_id, user_id=p.user_id, target=f.question[:120])
    await s.commit()
    return out(f)


@router.get("/forecasts/{forecast_id}")
async def get_forecast(forecast_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    return out(await own(s, p.org_id, forecast_id))


@router.put("/forecasts/{forecast_id}")
async def edit(forecast_id: str, body: ForecastIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if f.status != "draft":
        raise Conflict("A locked forecast can't be changed. Void it and create a new one if the question was wrong.", code="forecast_locked")
    if body.simulation_id:
        await get_sim(s, p, body.simulation_id)
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    await s.commit()
    return out(f)


@router.delete("/forecasts/{forecast_id}")
async def delete(forecast_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if f.status != "draft":
        raise Conflict("Locked forecasts stay on the record. Void it instead; voided forecasts remain visible.", code="forecast_locked")
    await s.delete(f)
    await s.commit()
    return {"ok": True}


@router.post("/forecasts/{forecast_id}/lock")
async def lock(forecast_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if f.status != "draft":
        raise Conflict("This forecast is already locked.", code="forecast_locked")
    if f.resolves_on <= tr.today():
        raise AppError("A forecast must be locked before the day it resolves.", code="too_late")
    if not f.simulation_id:
        raise AppError("Link a completed simulation that answers the question before locking.")
    sim = await get_sim(s, p, f.simulation_id)
    if sim.status != "completed":
        raise AppError("The linked simulation has not completed yet.")
    f.prediction = tr.snapshot(f, sim)
    f.locked_at, f.status = utcnow(), "locked"
    f.prediction_hash = tr.sha(tr.locked_payload(f))
    entry = await tr.append(s, "lock", "forecast", f.id, p.org_id, f.prediction_hash)
    audit.record(s, "forecast.lock", org_id=p.org_id, user_id=p.user_id, target=f.id, meta={"hash": f.prediction_hash, "seq": entry.seq})
    await s.commit()
    return out(f)


@router.post("/forecasts/{forecast_id}/resolve")
async def resolve(forecast_id: str, body: OutcomeIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if f.status != "locked":
        raise Conflict("Only a locked, unresolved forecast can be resolved.", code="not_locked")
    if tr.today() < f.resolves_on:
        raise AppError(f"This forecast resolves on {f.resolves_on.isoformat()}.", code="not_due")
    value = tr.check_outcome(f, body.value)
    f.outcome = {"value": value, "evidence_url": body.evidence_url, "note": body.note}
    f.resolved_at, f.resolved_by, f.status = utcnow(), p.user_id, "resolved"
    f.outcome_hash = tr.sha({"forecast": f.id, "prediction_hash": f.prediction_hash, "outcome": f.outcome,
                             "resolved_at": f.resolved_at.isoformat()})
    await tr.append(s, "resolve", "forecast", f.id, p.org_id, f.outcome_hash)
    audit.record(s, "forecast.resolve", org_id=p.org_id, user_id=p.user_id, target=f.id, meta={"value": value})
    await s.commit()
    return out(f)


@router.post("/forecasts/{forecast_id}/void")
async def void(forecast_id: str, body: VoidIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    f = await own(s, p.org_id, forecast_id)
    if f.status not in ("locked", "resolved"):
        raise Conflict("Only locked forecasts can be voided; delete a draft instead.")
    f.status, f.outcome = "void", {**(f.outcome or {}), "void_reason": body.reason}
    await tr.append(s, "void", "forecast", f.id, p.org_id, tr.sha({"forecast": f.id, "reason": body.reason}))
    audit.record(s, "forecast.void", org_id=p.org_id, user_id=p.user_id, target=f.id, meta={"reason": body.reason})
    await s.commit()
    return out(f)


@router.get("/forecasts/{forecast_id}/proof")
async def proof(forecast_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    """Everything needed to show a third party that this prediction existed, unchanged, before its outcome."""
    f = await own(s, p.org_id, forecast_id)
    if not f.locked_at:
        raise Conflict("Lock the forecast first.")
    entries = (await s.execute(select(LedgerEntry).where(LedgerEntry.subject_id == f.id).order_by(LedgerEntry.seq))).scalars().all()
    return {"payload": tr.canonical(tr.locked_payload(f)), "prediction_hash": f.prediction_hash,
            "ledger_entries": [tr.public_entry(e) for e in entries],
            "how_to_verify": "SHA-256 of `payload` equals `prediction_hash`, which appears in the public ledger entry for this forecast's "
                             "lock; each ledger entry's hash covers the previous one, so the entry cannot have been added later."}


# ---- public ----------------------------------------------------------------------------------------------------------
@router.get("/public/ledger")
async def ledger(request: Request, s: AsyncSession = Depends(get_session), after: int = 0, limit: int = 500):
    """Hashes only: anyone can recompute the chain. Workspace content is never in the ledger."""
    await hit("ledger:" + client_ip(request), 60)
    rows = (await s.execute(select(LedgerEntry).where(LedgerEntry.seq > after).order_by(LedgerEntry.seq)
                            .limit(max(1, min(limit, 1000))))).scalars().all()
    head = (await s.execute(select(LedgerEntry).order_by(LedgerEntry.seq.desc()).limit(1))).scalar_one_or_none()
    return {"entries": [tr.public_entry(e) for e in rows], "head": head.entry_hash if head else tr.GENESIS,
            "length": head.seq if head else 0, "genesis": tr.GENESIS,
            "entry_hash_covers": ["seq", "created_at", "action", "subject_type", "subject_id", "payload_hash", "prev_hash"],
            "encoding": "SHA-256 of JSON with sorted keys, no spaces, UTF-8"}


@router.get("/public/track-record")
async def public_record(request: Request, s: AsyncSession = Depends(get_session)):
    await hit("track-record:" + client_ip(request), 60)
    if not settings.public_track_record:
        raise NotFound("The public track record is not published yet.")
    rows = (await s.execute(select(Forecast).where(Forecast.public.is_(True), Forecast.status != "draft")
                            .order_by(Forecast.resolves_on.desc()))).scalars().all()
    records = [tr.record_of_forecast(f) for f in rows]
    return {"summary": tr.summarise(records), "records": [tr.published(r) for r in records]}
