"""Barometer library endpoints: upload with provenance, browse, search, download the original, delete."""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from sqlalchemy import and_, delete, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, principal, role, throttle
from app.core.config import settings
from app.core.errors import AppError, Forbidden, NotFound
from app.core.uploads import read_limited
from app.db.session import get_session
from app.models import BarometerChunk, BarometerDocument
from app.models.tenancy import ROLE_RANK
from app.services import audit, barometers, storage

router = APIRouter(tags=["barometers"])
UPLOAD_LIMIT_MB = 100


def doc_out(d: BarometerDocument) -> dict:
    return {"id": d.id, "title": d.title, "country": d.country, "publisher": d.publisher, "source_url": d.source_url,
            "published_on": d.published_on, "filename": d.filename, "mime": d.mime, "size": d.size, "sha256": d.sha256,
            "encoding": d.encoding, "status": d.status, "quarantine_reason": d.quarantine_reason, "text_chars": d.text_chars,
            "chunk_count": d.chunk_count, "notes": d.notes, "created_at": d.created_at,
            "scope": "shared" if d.org_id is None else "workspace"}


async def _visible(s: AsyncSession, p: Principal, doc_id: str) -> BarometerDocument:
    d = (await s.execute(select(BarometerDocument).where(and_(BarometerDocument.id == doc_id,
                                                              barometers.scope_filter(BarometerDocument, p.org_id))))).scalar_one_or_none()
    if not d:
        raise NotFound("Document not found.")
    return d


@router.get("/barometers")
async def list_documents(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), country: str = "",
                         status: str = "", q: str = "", limit: int = 200):
    conds = [barometers.scope_filter(BarometerDocument, p.org_id)]
    if country:
        conds.append(BarometerDocument.country == country.upper())
    if status in ("ready", "quarantined"):
        conds.append(BarometerDocument.status == status)
    if q.strip():
        like = f"%{q.strip().lower()[:100]}%"
        conds.append(func.lower(BarometerDocument.title).like(like) | func.lower(BarometerDocument.publisher).like(like))
    rows = (await s.execute(select(BarometerDocument).where(and_(*conds)).order_by(desc(BarometerDocument.created_at))
                            .limit(max(1, min(limit, 500))))).scalars().all()
    countries = (await s.execute(select(BarometerDocument.country, func.count()).where(
        barometers.scope_filter(BarometerDocument, p.org_id), BarometerDocument.status == "ready")
        .group_by(BarometerDocument.country))).all()
    return {"documents": [doc_out(d) for d in rows], "countries": {c: n for c, n in countries}}


@router.post("/barometers", dependencies=[Depends(throttle("uploads", "rate_limit_uploads_per_hour", 3600))])
async def upload(file: UploadFile = File(...), country: str = Form(...), publisher: str = Form(...), title: str = Form(""),
                 source_url: str = Form(""), published_on: str = Form(""), shared: bool = Form(False),
                 p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    if shared and not p.is_superuser:
        raise Forbidden("Only platform administrators add to the shared library.")
    try:
        when = date.fromisoformat(published_on) if published_on.strip() else None
    except ValueError:
        raise AppError("Publication date must look like 2026-03-31.", code="bad_published_on")
    data = await read_limited(file, min(settings.max_upload_mb, UPLOAD_LIMIT_MB) * 1024 * 1024)
    doc = await barometers.ingest(s, org_id=None if shared else p.org_id, user_id=p.user_id, filename=file.filename or "upload",
                                  data=data, provenance=barometers.Provenance(country, publisher, title, source_url or None, when))
    audit.record(s, "barometer.upload", org_id=p.org_id, user_id=p.user_id, target=doc.id,
                 meta={"status": doc.status, "shared": shared, "country": doc.country})
    await s.commit()
    return doc_out(doc)


@router.get("/barometers/search", dependencies=[Depends(throttle("expensive", "rate_limit_expensive_per_minute"))])
async def search(q: str, country: str = "", k: int = 8, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    if not q.strip():
        raise AppError("Type what you are looking for.")
    countries = [c.strip() for c in country.split(",") if c.strip()] or None
    return {"results": await barometers.search(s, p.org_id, q[:500], countries=countries, k=max(1, min(k, 25)))}


@router.get("/barometers/{doc_id}")
async def get_document(doc_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    d = await _visible(s, p, doc_id)
    preview = (await s.execute(select(BarometerChunk).where(BarometerChunk.document_id == d.id)
                               .order_by(BarometerChunk.ordinal).limit(5))).scalars().all()
    return {**doc_out(d), "preview": [{"location": c.location, "text": c.text[:2000]} for c in preview]}


@router.get("/barometers/{doc_id}/file")
async def download_original(doc_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    d = await _visible(s, p, doc_id)
    data = await storage.get(d.storage_key)
    safe = "".join(ch for ch in d.filename if ch.isalnum() or ch in "._- ")[:120] or "document"
    # Always a download, never rendered inline: originals come from the public internet.
    return Response(data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{safe}"', "X-Content-Type-Options": "nosniff",
                             "Cache-Control": "no-store"})


@router.delete("/barometers/{doc_id}")
async def delete_document(doc_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    d = await _visible(s, p, doc_id)
    if d.org_id is None and not p.is_superuser:
        raise Forbidden("Only platform administrators remove shared documents.")
    if d.org_id is not None and d.uploaded_by != p.user_id and ROLE_RANK[p.role] < ROLE_RANK["admin"]:
        raise Forbidden("Only the person who added this document or a workspace admin can remove it.")
    key = d.storage_key
    await s.execute(delete(BarometerChunk).where(BarometerChunk.document_id == d.id))
    await s.delete(d)
    audit.record(s, "barometer.delete", org_id=p.org_id, user_id=p.user_id, target=doc_id)
    await s.commit()
    await storage.delete(key)
    return {"ok": True}
