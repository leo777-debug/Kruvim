"""Barometer library: ingest public country data with provenance, retrieve it for agents."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, Conflict
from app.core.uploads import parse_off_loop
from app.db.base import utcnow
from app.models import BarometerChunk, BarometerDocument
from app.services import storage
from app.services.datapool.retrieval import embed

from .extract import ACCEPTED_EXT, Quarantine, chunks, extract

COUNTRY = re.compile(r"^(GLOBAL|[A-Z]{2}(-[A-Z0-9]{1,3})?)$")
MIME = {".csv": "text/csv", ".tsv": "text/tab-separated-values", ".txt": "text/plain", ".md": "text/markdown",
        ".json": "application/json", ".xml": "application/xml", ".html": "text/html", ".htm": "text/html", ".pdf": "application/pdf",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@dataclass
class Provenance:
    country: str
    publisher: str
    title: str = ""
    source_url: str | None = None
    published_on: date | None = None


def check_provenance(p: Provenance) -> Provenance:
    country = (p.country or "").strip().upper()
    if not COUNTRY.match(country):
        raise AppError("Country must be a two-letter code such as AE, FR or US (or a region code like AE-DU, or GLOBAL).",
                       code="bad_country")
    publisher = (p.publisher or "").strip()
    if not publisher:
        raise AppError("Say who published this data (for example the national statistics office).", code="publisher_required")
    url = (p.source_url or "").strip() or None
    if url and not re.match(r"^https?://[^\s/]+", url):
        raise AppError("The source link must start with http:// or https://.", code="bad_source_url")
    if p.published_on and p.published_on > date.today():
        raise AppError("The publication date cannot be in the future.", code="bad_published_on")
    return Provenance(country, publisher[:240], (p.title or "").strip()[:300], url and url[:1000], p.published_on)


def scope_filter(model, org_id: str):
    """A workspace sees its own documents and the shared library."""
    return or_(model.org_id == org_id, model.org_id.is_(None))


async def ingest(s: AsyncSession, *, org_id: str | None, user_id: str | None, filename: str, data: bytes,
                 provenance: Provenance) -> BarometerDocument:
    """Store the original untouched, then index its verbatim text. Unreadable files are kept but quarantined."""
    name = os.path.basename(filename or "upload")[:300] or "upload"
    ext = os.path.splitext(name.lower())[1]
    if ext not in ACCEPTED_EXT:
        raise AppError(f"{ext or 'Files without an extension'} cannot be added. Use CSV, TSV, XLSX, JSON, PDF, DOCX, TXT, "
                       "Markdown, HTML or XML.", code="unsupported_type", status=415)
    p = check_provenance(provenance)
    digest = hashlib.sha256(data).hexdigest()
    same = (await s.execute(select(BarometerDocument).where(
        BarometerDocument.sha256 == digest,
        or_(BarometerDocument.org_id.is_(None), BarometerDocument.org_id == org_id) if org_id else BarometerDocument.org_id.is_(None),
    ).limit(1))).scalar_one_or_none()
    if same:
        where = "the shared library" if same.org_id is None else "your workspace"
        raise Conflict(f"This exact file is already in {where} as \"{same.title}\".", code="duplicate",
                       details={"document_id": same.id})

    doc = BarometerDocument(org_id=org_id, title=p.title or os.path.splitext(name)[0], country=p.country, publisher=p.publisher,
                            source_url=p.source_url, published_on=p.published_on, filename=name, mime=MIME[ext], size=len(data),
                            sha256=digest, storage_key=f"{org_id or 'shared'}/barometers/{uuid.uuid4().hex}{ext}",
                            status="ready", text_chars=0, chunk_count=0, notes={}, uploaded_by=user_id)
    await storage.put(doc.storage_key, data)
    try:
        extracted = await parse_off_loop(extract, name, data)
    except Quarantine as exc:
        doc.status, doc.quarantine_reason = "quarantined", str(exc)
        s.add(doc)
        await s.flush()
        return doc
    pieces = chunks(extracted)
    doc.encoding, doc.notes, doc.text_chars, doc.chunk_count = extracted.encoding, extracted.notes, extracted.chars, len(pieces)
    s.add(doc)
    await s.flush()
    now = utcnow()
    vectors = await parse_off_loop(lambda: [embed(f"{p.publisher} {p.country} {c.text}").tolist() for c in pieces])
    s.add_all(BarometerChunk(document_id=doc.id, org_id=org_id, country=p.country, ordinal=i, location=c.location[:120] or "whole file",
                             text=c.text, embedding=v, created_at=now) for i, (c, v) in enumerate(zip(pieces, vectors)))
    return doc


def _countries(codes: list[str] | None) -> list[str] | None:
    if not codes:
        return None
    wanted = {c.upper() for c in codes} | {c.upper()[:2] for c in codes} | {"GLOBAL"}
    return sorted(wanted)


async def search(s: AsyncSession, org_id: str, query: str, *, countries: list[str] | None = None, k: int = 8) -> list[dict]:
    """The chunks most related to `query`, from this workspace's documents and the shared library."""
    qv = embed(query)
    conds = [scope_filter(BarometerChunk, org_id), BarometerDocument.status == "ready"]
    if wanted := _countries(countries):
        conds.append(BarometerChunk.country.in_(wanted))
    base = select(BarometerChunk, BarometerDocument).join(BarometerDocument, BarometerDocument.id == BarometerChunk.document_id) \
        .where(and_(*conds))
    if s.bind.dialect.name == "postgresql":
        rows = (await s.execute(base.order_by(BarometerChunk.embedding.cosine_distance(qv.tolist())).limit(k))).all()
        scored = [(float(np.asarray(c.embedding, dtype=np.float32) @ qv), c, d) for c, d in rows]
    else:
        rows = (await s.execute(base.limit(20_000))).all()
        scored = sorted(((float(np.asarray(c.embedding, dtype=np.float32) @ qv), c, d) for c, d in rows), key=lambda x: -x[0])[:k]
    return [excerpt(c, d, score) for score, c, d in scored]


def excerpt(c: BarometerChunk, d: BarometerDocument, score: float | None = None) -> dict:
    return {"chunk_id": c.id, "document_id": d.id, "title": d.title, "publisher": d.publisher, "country": c.country,
            "published_on": d.published_on.isoformat() if d.published_on else None, "source_url": d.source_url,
            "filename": d.filename, "location": c.location, "text": c.text, "scope": "shared" if d.org_id is None else "workspace",
            **({"score": round(score, 4)} if score is not None else {})}


def world_lines(excerpts: list[dict], per_excerpt: int = 700) -> str:
    """How agents see barometer data: unedited excerpts, each tagged with where it came from."""
    if not excerpts:
        return ""
    out = ["Public information people in these places may have come across (published data and reports, unedited; "
           "it can be incomplete, outdated or contradictory, and people interpret it differently):"]
    for x in excerpts:
        when = f", {x['published_on']}" if x.get("published_on") else ""
        out.append(f"- [{x['publisher']}, {x['country']}{when}, {x['title']} ({x['location']})] {x['text'][:per_excerpt]}")
    return "\n".join(out)
