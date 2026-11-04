from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_project, principal, role
from app.core.config import settings
from app.core.errors import AppError, NotFound
from app.db.session import get_session
from app.models import Asset, Project, Simulation
from app.schemas.workspace import ProjectIn, ProjectUpdate
from app.services import audit, storage
from app.services.content import ContentError, document_text

router = APIRouter(tags=["projects"])


class LinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)


@router.post('/projects/{project_id}/import-link')
async def from_link(project_id: str, body: LinkIn, p: Principal = Depends(role('member')), s: AsyncSession = Depends(get_session)):
    await get_project(s, p, project_id)
    from app.services.content.links import import_link
    result = await import_link(body.url)
    audit.record(s, 'content.import_link', org_id=p.org_id, user_id=p.user_id, target=project_id)
    await s.commit()
    return result
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
ALLOWED = {
    "content": {"video/", "audio/", "image/", "text/", "application/pdf", DOCX},
    "content_b": {"video/", "audio/", "image/", "text/", "application/pdf", DOCX},
    "seed": {"text/", "application/pdf", "application/json", "text/markdown", DOCX},
}
SEED_EXT = {".txt", ".md", ".pdf", ".docx", ".csv", ".json", ".srt", ".vtt"}
DOC_EXT = {".txt", ".md", ".pdf", ".docx"}


def _project(pr: Project, sims: int = 0, last=None) -> dict:
    return {"id": pr.id, "name": pr.name, "description": pr.description, "archived": pr.archived, "created_at": pr.created_at,
            "simulations": sims, "last_activity": last}


@router.get("/projects")
async def list_projects(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session), archived: bool = False):
    rows = (await s.execute(select(Project, func.count(Simulation.id), func.max(Simulation.updated_at))
                            .outerjoin(Simulation, Simulation.project_id == Project.id)
                            .where(and_(Project.org_id == p.org_id, Project.archived.is_(archived)))
                            .group_by(Project.id).order_by(desc(Project.created_at)))).all()
    return [_project(pr, n, last) for pr, n, last in rows]


@router.post("/projects")
async def create_project(body: ProjectIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    pr = Project(org_id=p.org_id, name=body.name, description=body.description, created_by=p.user_id)
    s.add(pr)
    audit.record(s, "project.create", org_id=p.org_id, user_id=p.user_id, target=pr.name)
    await s.commit()
    return _project(pr)


@router.get("/projects/{project_id}")
async def get_project_route(project_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    pr = await get_project(s, p, project_id)
    sims = (await s.execute(select(Simulation).where(Simulation.project_id == pr.id).order_by(desc(Simulation.created_at)))).scalars().all()
    assets = (await s.execute(select(Asset).where(Asset.project_id == pr.id).order_by(desc(Asset.created_at)))).scalars().all()
    return {**_project(pr, len(sims)), "simulations": [sim_summary(x) for x in sims], "assets": [asset_out(a) for a in assets]}


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, body: ProjectUpdate, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    pr = await get_project(s, p, project_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(pr, k, v)
    await s.commit()
    return _project(pr)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    pr = await get_project(s, p, project_id)
    running = (await s.execute(select(func.count()).select_from(Simulation).where(and_(
        Simulation.project_id == pr.id, Simulation.status.in_(["queued", "running", "paused"]))))).scalar()
    if running:
        raise AppError("Stop running simulations before deleting the project.", code="conflict", status=409)
    for a in (await s.execute(select(Asset).where(Asset.project_id == pr.id))).scalars():
        await storage.delete(a.storage_key)
    await s.delete(pr)
    audit.record(s, "project.delete", org_id=p.org_id, user_id=p.user_id, target=pr.name)
    await s.commit()
    return {"ok": True}


def asset_out(a: Asset) -> dict:
    return {"id": a.id, "kind": a.kind, "filename": a.filename, "mime": a.mime, "size": a.size, "created_at": a.created_at,
            "excerpt": (a.text_excerpt or "")[:300]}


@router.post("/projects/{project_id}/assets")
async def upload_asset(project_id: str, file: UploadFile = File(...), kind: str = Form("content"),
                       p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    pr = await get_project(s, p, project_id)
    if kind not in ALLOWED:
        raise AppError("kind must be content, content_b or seed")
    mime = (file.content_type or "application/octet-stream").lower()
    ext = os.path.splitext(file.filename or "")[1].lower()
    if not any(mime.startswith(m) for m in ALLOWED[kind]) and not (kind == "seed" and ext in SEED_EXT) and ext not in DOC_EXT:
        raise AppError(f"File type {mime} is not accepted for {kind}.", code="unsupported_media", status=415)
    data = bytearray()
    limit = settings.max_upload_mb * 1024 * 1024
    while chunk := await file.read(1 << 20):
        data.extend(chunk)
        if len(data) > limit:
            raise AppError(f"File larger than {settings.max_upload_mb} MB.", code="too_large", status=413)
    key = f"{p.org_id}/{pr.id}/{uuid.uuid4().hex}{ext[:10]}"
    await storage.put(key, bytes(data))
    excerpt = ""
    if kind == "seed" or ext in DOC_EXT:
        try:
            excerpt = document_text(bytes(data), file.filename or "")
        except ContentError as exc:
            raise AppError(str(exc), code="unreadable", status=422)
    a = Asset(org_id=p.org_id, project_id=pr.id, kind=kind, filename=(file.filename or "upload")[:300], mime=mime, size=len(data),
              storage_key=key, text_excerpt=excerpt, uploaded_by=p.user_id)
    s.add(a)
    await s.commit()
    return asset_out(a)


@router.delete("/assets/{asset_id}")
async def delete_asset(asset_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    a = (await s.execute(select(Asset).where(and_(Asset.id == asset_id, Asset.org_id == p.org_id)))).scalar_one_or_none()
    if not a:
        raise NotFound("Asset not found.")
    await storage.delete(a.storage_key)
    await s.delete(a)
    await s.commit()
    return {"ok": True}


def sim_summary(x: Simulation) -> dict:
    r = x.results or {}
    return {"id": x.id, "project_id": x.project_id, "name": x.name, "status": x.status, "step": x.step, "report_status": x.report_status,
            "content_type": (x.content or {}).get("type"), "platform": (x.content or {}).get("platform"), "ab": bool((x.content or {}).get("variant_b")),
            "regions": (x.audience or {}).get("regions") or [], "created_at": x.created_at, "updated_at": x.updated_at,
            "progress": x.progress, "score": (r.get("score") or {}).get("mean"), "viral": (r.get("viral") or {}).get("score"),
            "ab_winner": (r.get("ab") or {}).get("winner"), "error": x.error, "credits_estimate": x.credits_estimate,
            "dry": bool((r.get("provider") or {}).get("dry")), "format": (x.content or {}).get("format"),
            "b_kind": (x.content or {}).get("b_kind") or "version", "parent_id": x.parent_id, "review_status": x.review_status,
            "rerun_every_days": x.rerun_every_days, "next_rerun_at": x.next_rerun_at, "autopilot": bool((x.config or {}).get("autopilot")),
            "watch_id": (x.config or {}).get("watch_id")}
