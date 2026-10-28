"""Platform admin for the beta: invite codes, users, usage, failed jobs, uploaded data, errors; and browser error reports."""
from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, superuser
from app.core.config import settings
from app.core.errors import Conflict, NotFound
from app.core.ratelimit import hit
from app.core.security import decode_access_token, sha256
from app.db.base import utcnow
from app.db.session import get_session
from app.models import (
    Asset,
    BarometerDocument,
    BetaInvite,
    Dataset,
    ErrorEvent,
    Membership,
    Organization,
    RefreshToken,
    Simulation,
    UsageEvent,
    User,
)
from app.schemas.auth import Email
from app.services import audit, spend
from app.services.ops import record_error

router = APIRouter(tags=["admin"])


class InviteIn(BaseModel):
    email: Email | None = None
    note: str = Field(default="", max_length=300)
    max_uses: int = Field(default=1, ge=1, le=500)
    days: int = Field(default=30, ge=1, le=365)


class UserPatch(BaseModel):
    is_active: bool


class ClientErrorIn(BaseModel):
    message: str = Field(max_length=500)
    detail: str = Field(default="", max_length=4000)
    path: str = Field(default="", max_length=300)


def invite_out(i: BetaInvite) -> dict:
    now = utcnow()
    state = ("revoked" if i.revoked_at else "used up" if i.uses >= i.max_uses
             else "expired" if i.expires_at.replace(tzinfo=UTC) < now else "active")
    return {"id": i.id, "email": i.email, "note": i.note, "max_uses": i.max_uses, "uses": i.uses, "expires_at": i.expires_at,
            "created_at": i.created_at, "state": state}


# ---- beta invites ------------------------------------------------------------------------------------------------------
@router.get("/admin/beta-invites")
async def list_invites(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(BetaInvite).order_by(desc(BetaInvite.created_at)).limit(500))).scalars().all()
    return {"invites": [invite_out(i) for i in rows], "registration_open": settings.registration_open,
            "allowlist": settings.signup_allowlist}


@router.post("/admin/beta-invites")
async def create_invite(body: InviteIn, user: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    code = "KRV-" + secrets.token_urlsafe(9).replace("-", "x").replace("_", "y").upper()
    i = BetaInvite(code_hash=sha256(code), email=body.email, note=body.note, max_uses=body.max_uses, uses=0,
                   expires_at=utcnow() + timedelta(days=body.days), created_by=user.id)
    s.add(i)
    audit.record(s, "beta_invite.create", user_id=user.id, target=body.email or body.note or "open code", meta={"max_uses": body.max_uses})
    await s.commit()
    return {**invite_out(i), "code": code, "signup_url": f"{settings.public_url.rstrip('/')}/register?code={code}",
            "note_shown_once": "Copy the code now; only its hash is stored."}


@router.delete("/admin/beta-invites/{invite_id}")
async def revoke_invite(invite_id: str, user: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    i = await s.get(BetaInvite, invite_id)
    if not i:
        raise NotFound("Invite not found.")
    i.revoked_at = utcnow()
    audit.record(s, "beta_invite.revoke", user_id=user.id, target=i.id)
    await s.commit()
    return invite_out(i)


# ---- users ---------------------------------------------------------------------------------------------------------------
@router.get("/admin/users")
async def users(_: User = Depends(superuser), s: AsyncSession = Depends(get_session), q: str = "", limit: int = 200):
    query = select(User).order_by(desc(User.created_at)).limit(max(1, min(limit, 1000)))
    if q.strip():
        like = f"%{q.strip().lower()[:100]}%"
        query = query.where(or_(func.lower(User.email).like(like), func.lower(User.name).like(like)))
    rows = (await s.execute(query)).scalars().all()
    orgs = (await s.execute(select(Membership.user_id, Organization.name).join(Organization, Organization.id == Membership.org_id)
                            .where(Membership.user_id.in_([u.id for u in rows])))).all() if rows else []
    by_user: dict[str, list[str]] = {}
    for uid, name in orgs:
        by_user.setdefault(uid, []).append(name)
    return [{"id": u.id, "email": u.email, "name": u.name, "is_active": u.is_active, "is_superuser": u.is_superuser,
             "created_at": u.created_at, "last_login_at": u.last_login_at, "workspaces": by_user.get(u.id, [])} for u in rows]


@router.patch("/admin/users/{user_id}")
async def update_user(user_id: str, body: UserPatch, admin: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    u = await s.get(User, user_id)
    if not u:
        raise NotFound("User not found.")
    if u.id == admin.id and not body.is_active:
        raise Conflict("You can't disable your own account.")
    u.is_active = body.is_active
    if not body.is_active:   # end their sessions now, not when the access token expires
        for t in (await s.execute(select(RefreshToken).where(and_(RefreshToken.user_id == u.id, RefreshToken.revoked_at.is_(None))))).scalars():
            t.revoked_at = utcnow()
    audit.record(s, "user.enable" if body.is_active else "user.disable", user_id=admin.id, target=u.email)
    await s.commit()
    return {"id": u.id, "is_active": u.is_active}


# ---- usage, failed jobs, data, errors --------------------------------------------------------------------------------------
@router.get("/admin/usage")
async def usage(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (await s.execute(select(Organization.id, Organization.name, Organization.plan, Organization.credits_balance,
                                   func.coalesce(func.sum(UsageEvent.quantity), 0), func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                                   func.coalesce(func.sum(UsageEvent.output_tokens), 0), func.sum(UsageEvent.cost_usd))
                            .outerjoin(UsageEvent, and_(UsageEvent.org_id == Organization.id, UsageEvent.created_at >= month))
                            .group_by(Organization.id, Organization.name, Organization.plan, Organization.credits_balance))).all()
    orgs = sorted(({"id": i, "name": n, "plan": p, "credits_balance": c, "calls": int(q), "input_tokens": int(it), "output_tokens": int(ot),
                    "cost_usd": round(cost, 4) if cost is not None else None} for i, n, p, c, q, it, ot, cost in rows),
                  key=lambda x: -x["calls"])
    return {"month": month.date().isoformat(), "orgs": orgs, "shared_key_today": await spend.platform_calls_today()}


@router.get("/admin/failed-jobs")
async def failed_jobs(_: User = Depends(superuser), s: AsyncSession = Depends(get_session), days: int = 14):
    since = utcnow() - timedelta(days=max(1, min(days, 90)))
    rows = (await s.execute(select(Simulation, Organization.name).join(Organization, Organization.id == Simulation.org_id)
                            .where(Simulation.updated_at >= since, or_(Simulation.status == "failed", Simulation.report_status == "failed"))
                            .order_by(desc(Simulation.updated_at)).limit(200))).all()
    return [{"id": sim.id, "name": sim.name, "workspace": org, "status": sim.status, "report_status": sim.report_status,
             "error": sim.error, "updated_at": sim.updated_at} for sim, org in rows]


@router.get("/admin/data")
async def data(_: User = Depends(superuser), s: AsyncSession = Depends(get_session)):
    docs = dict((await s.execute(select(BarometerDocument.status, func.count()).group_by(BarometerDocument.status))).all())
    size = (await s.execute(select(func.coalesce(func.sum(BarometerDocument.size), 0)))).scalar()
    quarantined = (await s.execute(select(BarometerDocument, Organization.name).outerjoin(Organization, Organization.id == BarometerDocument.org_id)
                                   .where(BarometerDocument.status == "quarantined").order_by(desc(BarometerDocument.created_at)).limit(50))).all()
    assets = (await s.execute(select(func.count(), func.coalesce(func.sum(Asset.size), 0)))).one()
    return {"barometers": {"ready": docs.get("ready", 0), "quarantined": docs.get("quarantined", 0), "bytes": int(size)},
            "assets": {"count": assets[0], "bytes": int(assets[1])},
            "datasets": (await s.execute(select(func.count()).select_from(Dataset))).scalar(),
            "recent_quarantined": [{"id": d.id, "title": d.title, "filename": d.filename, "reason": d.quarantine_reason,
                                    "workspace": org or "shared library", "created_at": d.created_at} for d, org in quarantined]}


@router.get("/admin/errors")
async def errors(_: User = Depends(superuser), s: AsyncSession = Depends(get_session), source: str = ""):
    q = select(ErrorEvent).order_by(desc(ErrorEvent.created_at)).limit(200)
    if source in ("server", "job", "client"):
        q = q.where(ErrorEvent.source == source)
    since = utcnow() - timedelta(days=1)
    counts = dict((await s.execute(select(ErrorEvent.source, func.count()).where(ErrorEvent.created_at >= since).group_by(ErrorEvent.source))).all())
    return {"last_24h": counts, "events": [{"id": e.id, "source": e.source, "message": e.message, "detail": e.detail, "path": e.path,
                                            "request_id": e.request_id, "created_at": e.created_at} for e in (await s.execute(q)).scalars()]}


# ---- browser error reports ---------------------------------------------------------------------------------------------------
@router.post("/client-errors", status_code=204)
async def client_error(body: ClientErrorIn, request: Request):
    """The web app reports its own crashes here (no third-party tracker); rate-limited, works signed in or out."""
    await hit("client-errors:" + client_ip(request), 20)
    user_id = None
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        try:
            user_id = decode_access_token(auth.split(" ", 1)[1]).get("sub")
        except Exception:
            user_id = None
    await record_error("client", body.message, detail=body.detail, path=body.path, user_id=user_id,
                       request_id=request.headers.get("x-request-id"))
