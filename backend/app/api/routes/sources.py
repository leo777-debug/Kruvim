"""Public reference registry. Workspace uploads remain private; publication requires a platform admin."""
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, principal
from app.core.errors import AppError, Forbidden, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import DataSource, SourceObservation
from app.services import audit, storage
from app.services.sources import ensure_sources, payload, store_observations
from app.services.sources.adapters import ADAPTERS

router = APIRouter(prefix="/sources", tags=["sources"])


class SourceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=240)
    publisher: str = Field(min_length=1, max_length=240)
    country: str = Field(min_length=1, max_length=8)
    geography_level: Literal["country", "emirate", "district", "point"]
    url: str = Field(min_length=1, max_length=2000, pattern=r"^https://")
    access_method: Literal["api", "file_download", "portal_registration", "report_pdf", "manual"]
    licence: str = Field(min_length=1, max_length=10000)
    attribution: str = Field(min_length=1, max_length=10000)
    cadence: Literal["annual", "quarterly", "monthly", "daily", "irregular"]
    reliability: float = Field(default=.5, ge=0, le=1, allow_inf_nan=False)
    notes: str = Field(default="", max_length=20000)
    status: Literal["active", "pending_import", "placeholder", "deprecated"] = "pending_import"
    attributes: list[str] = Field(default_factory=list, max_length=100)
    terms_url: str = Field(default="", max_length=2000)
    config: dict = Field(default_factory=dict)


class SourcePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=240)
    licence: str | None = Field(default=None, min_length=1, max_length=10000)
    attribution: str | None = Field(default=None, min_length=1, max_length=10000)
    reliability: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=20000)
    status: Literal["active", "pending_import", "placeholder", "deprecated"] | None = None
    licence_approved: bool | None = None
    approval_note: str = Field(default="", max_length=4000)
    config: dict | None = None


def admin(p):
    if not p.is_superuser:
        raise Forbidden("Only platform administrators may publish or edit public reference data.")


async def find(s, source_id):
    row = await s.get(DataSource, source_id)
    if not row:
        raise NotFound("Source not found.")
    return row


@router.get("")
async def list_sources(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await ensure_sources(s)
    rows = (await s.execute(select(DataSource).order_by(DataSource.country, DataSource.name))).scalars().all()
    counts = dict((await s.execute(select(SourceObservation.source_id, func.count()).group_by(SourceObservation.source_id))).all())
    latest = dict((await s.execute(select(SourceObservation.source_id, func.max(SourceObservation.retrieved_at))
                                  .group_by(SourceObservation.source_id))).all())
    await s.commit()
    return [{**payload(r), "observations": counts.get(r.id, 0), "last_imported_at": latest.get(r.id)} for r in rows]


@router.post("")
async def create_source(body: SourceEdit, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    admin(p)
    await ensure_sources(s)
    if (await s.execute(select(DataSource.id).where(DataSource.key == body.key))).scalar_one_or_none():
        raise AppError("That source key is already registered.", status=409)
    row = DataSource(**body.model_dump())
    s.add(row)
    await s.flush()
    audit.record(s, "source.create", org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return payload(row)


@router.patch("/{source_id}")
async def edit_source(source_id: str, body: SourcePatch, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    admin(p)
    row = await find(s, source_id)
    changes = body.model_dump(exclude_none=True, exclude={"approval_note"})
    # Changing the licence invalidates the previous grant unless re-approved explicitly.
    if "licence" in changes and changes["licence"] != row.licence:
        changes.setdefault("licence_approved", False)
    if "config" in changes and changes["config"] != row.config:
        changes.setdefault("licence_approved", False)
    if changes.get("licence_approved") and (not row.licence_approved or changes.get("licence", row.licence) != row.licence or body.approval_note.strip()):
        if not body.approval_note.strip():
            raise AppError("Record the commercial reuse grant or licence evidence in the approval note.")
        row.licence_approved_by, row.licence_approved_at = p.user_id, utcnow()
        changes["notes"] = changes.get("notes", row.notes) + "\nCommercial reuse approval: " + body.approval_note.strip()
    elif changes.get("licence_approved") is False:
        row.licence_approved_by, row.licence_approved_at = None, None
    for key, value in changes.items():
        setattr(row, key, value)
    audit.record(s, "source.update", org_id=p.org_id, user_id=p.user_id, target=row.id,
                 meta={"fields": list(changes), "approval_note": body.approval_note})
    await s.commit()
    return payload(row)


@router.delete("/{source_id}")
async def deprecate_source(source_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    admin(p)
    row = await find(s, source_id)
    row.status = "deprecated"
    audit.record(s, "source.deprecate", org_id=p.org_id, user_id=p.user_id, target=row.id)
    await s.commit()
    return payload(row)


@router.get("/{source_id}/observations")
async def observations(source_id: str, metric: str | None = None, limit: int = 100,
                       p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await find(s, source_id)
    query = select(SourceObservation).where(SourceObservation.source_id == source_id)
    if metric:
        query = query.where(SourceObservation.metric == metric)
    rows = (await s.execute(query.order_by(desc(SourceObservation.period_end), SourceObservation.id)
                           .limit(max(1, min(limit, 1000))))).scalars().all()
    return [{key: getattr(r, key) for key in ("id", "source_id", "metric", "dimensions", "value", "unit",
             "period_start", "period_end", "geography", "retrieved_at", "raw_ref")} for r in rows]


@router.post("/{source_id}/fetch")
async def fetch_source(source_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    admin(p)
    row = await find(s, source_id)
    adapter = ADAPTERS.get(row.config.get("adapter"))
    if not adapter or row.status in ("deprecated", "placeholder"):
        raise AppError("This source needs a manual file import. See its download instructions.")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            fetched = await adapter.fetch(row, client)
        records, missing = adapter.parse(fetched, row)
    except (ValueError, httpx.HTTPError, OSError, KeyError) as exc:
        raise AppError(f"Source import failed: {exc}", status=422) from exc
    if not records:
        raise AppError("The feed contains no figures for this geography. Nothing was invented or filled.")
    key = f"sources/{row.id}/{utcnow().strftime('%Y%m%d%H%M%S%f')}/{fetched.filename.split('/')[-1]}"
    await storage.put(key, fetched.raw)
    count = await store_observations(s, row, records, "object:" + key)
    audit.record(s, "source.fetch", org_id=p.org_id, user_id=p.user_id, target=row.id,
                 meta={"url": fetched.url, "observations": count, "missing_cells": missing})
    await s.commit()
    return {"observations": count, "missing_cells": missing, "production_eligible": payload(row)["production_eligible"]}
