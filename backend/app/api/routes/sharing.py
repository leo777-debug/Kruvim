from __future__ import annotations

import asyncio
import io
import secrets
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_sim, principal, role
from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.core.ratelimit import hit
from app.core.security import sha256
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Organization, Report, ResultShare, Simulation
from app.services import audit
from app.services.monitoring import fetch
from app.services.report.citations import present_report
from app.services.report.exports import export_report

router = APIRouter(tags=["report downloads and sharing"])
PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}


class ShareIn(BaseModel):
    days: int = Field(default=7, ge=1, le=30)


def share_summary(row):
    return {"id": row.id, "created_at": row.created_at, "expires_at": row.expires_at,
            "revoked_at": row.revoked_at, "view_count": row.view_count}


async def ready_report(s, sim):
    report = (await s.execute(select(Report).where(Report.simulation_id == sim.id, Report.status == "done")
                            .order_by(Report.created_at.desc()).limit(1))).scalar_one_or_none()
    if sim.status != "completed" or not report:
        raise Conflict("Complete the simulation and report first.")
    return report


@router.get("/simulations/{sim_id}/report/download")
async def download(sim_id: str, format: Literal["pdf", "docx", "md"] = "pdf", p: Principal = Depends(principal),
                   s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    report = await ready_report(s, sim)
    branding = (p.org.settings or {}).get("branding") or {}
    logo = None
    if branding.get("logo_url") and format != "md":
        try:
            raw = await fetch(branding["logo_url"])
            with Image.open(io.BytesIO(raw)) as im:
                if im.width * im.height > 4_000_000:
                    raise ValueError("Oversized logo")
                im.thumbnail((400, 400))
                out = io.BytesIO()
                im.convert("RGBA").save(out, "PNG")
                logo = out.getvalue()
        except Exception:
            # A broken remote logo must not prevent a branded report download.
            logo = None
    readable = await present_report(s, report, p.org_id, private=False)
    data = await asyncio.to_thread(export_report, readable["rendered_markdown"], sim.results or {}, branding, format, logo)
    media = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "md": "text/markdown; charset=utf-8"}[format]
    return Response(data, media_type=media, headers={**PRIVATE_HEADERS, "Content-Disposition": f'attachment; filename="report-{sim.id}.{format}"'})


@router.post("/simulations/{sim_id}/shares")
async def create_share(sim_id: str, body: ShareIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    await ready_report(s, sim)
    token = secrets.token_urlsafe(32)
    row = ResultShare(org_id=p.org_id, simulation_id=sim.id, token_hash=sha256(token), expires_at=utcnow() + timedelta(days=body.days))
    s.add(row)
    audit.record(s, "results.share", org_id=p.org_id, user_id=p.user_id, target=sim.id)
    await s.commit()
    return {**share_summary(row), "url": settings.public_url.rstrip("/") + "/share/" + token}


@router.get("/simulations/{sim_id}/shares")
async def list_shares(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(ResultShare).where(ResultShare.simulation_id == sim_id, ResultShare.org_id == p.org_id)
                           .order_by(ResultShare.created_at.desc()))).scalars().all()
    return [share_summary(x) for x in rows]


@router.delete("/simulations/{sim_id}/shares/{share_id}")
async def revoke_share(sim_id: str, share_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    row = (await s.execute(select(ResultShare).where(ResultShare.id == share_id, ResultShare.simulation_id == sim_id,
                                                    ResultShare.org_id == p.org_id))).scalar_one_or_none()
    if not row:
        raise NotFound("Share link not found.")
    row.revoked_at = utcnow()
    audit.record(s, "results.unshare", org_id=p.org_id, user_id=p.user_id, target=sim_id)
    await s.commit()
    return {"ok": True}


@router.get("/shared-results/{token}")
async def public_results(token: str, request: Request, response: Response, s: AsyncSession = Depends(get_session)):
    await hit("result-share:" + (request.client.host if request.client else "unknown"), 120)
    if len(token) != 43:
        raise NotFound("This share link is unavailable or expired.")
    row = (await s.execute(select(ResultShare).where(ResultShare.token_hash == sha256(token),
            ResultShare.revoked_at.is_(None), ResultShare.expires_at > utcnow()))).scalar_one_or_none()
    if not row:
        raise NotFound("This share link is unavailable or expired.")
    sim = (await s.execute(select(Simulation).where(Simulation.id == row.simulation_id, Simulation.org_id == row.org_id))).scalar_one_or_none()
    if not sim:
        raise NotFound("This share link is unavailable or expired.")
    report = await ready_report(s, sim)
    org = await s.get(Organization, row.org_id)
    # Conditional atomic update means revocation/expiry wins even during an in-flight view.
    viewed = await s.execute(update(ResultShare).where(ResultShare.id == row.id, ResultShare.revoked_at.is_(None),
                            ResultShare.expires_at > utcnow()).values(view_count=ResultShare.view_count + 1))
    if not viewed.rowcount:
        raise NotFound("This share link is unavailable or expired.")
    await s.commit()
    response.headers.update(PRIVATE_HEADERS)
    readable = await present_report(s, report, row.org_id, private=False)
    allowed = ("score", "heatmap", "groups", "winners", "losers", "audience", "viral", "ab", "psychology", "provider")
    return {"name": sim.name, "finished_at": sim.finished_at, "expires_at": row.expires_at,
            "branding": (org.settings or {}).get("branding") or {},
            "results": {k: sim.results[k] for k in allowed if k in (sim.results or {})},
            "report": {"title": report.title, "summary": readable["rendered_summary"], "markdown": readable["rendered_markdown"],
                       "sources": readable["summary_sources"], "sections": readable["rendered_sections"]}}
