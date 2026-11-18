from __future__ import annotations

import re
import secrets
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy import and_, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, current_user
from app.core.config import settings
from app.core.errors import Conflict, Forbidden, NotFound, Unauthorized
from app.core.ratelimit import hit
from app.core.security import create_access_token, hash_password, new_refresh_token, sha256, verify_password
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Invite, Membership, Organization, RefreshToken, User
from app.schemas.auth import (
    AcceptInviteIn,
    AccountTokenIn,
    ChangePasswordIn,
    EmailRequestIn,
    LoginIn,
    OrgOut,
    RefreshIn,
    RegisterIn,
    ResetPasswordIn,
    SessionOut,
    UserOut,
)
from app.services import account_security, audit, mail
from app.services.quotas import ensure_monthly_grant, plan

router = APIRouter(prefix="/auth", tags=["auth"])


def _slug(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "workspace"
    return f"{base}-{secrets.token_hex(3)}"


async def _orgs(s: AsyncSession, user: User) -> list[OrgOut]:
    rows = (await s.execute(select(Membership, Organization).join(Organization, Organization.id == Membership.org_id)
                            .where(Membership.user_id == user.id).order_by(Membership.created_at))).all()
    return [OrgOut(id=o.id, name=o.name, slug=o.slug, plan=o.plan, role=m.role, credits_balance=o.credits_balance) for m, o in rows]


async def _session(s: AsyncSession, user: User, request: Request, org_id: str | None = None) -> SessionOut:
    orgs = await _orgs(s, user)
    raw, hashed = new_refresh_token()
    s.add(RefreshToken(user_id=user.id, token_hash=hashed, expires_at=utcnow() + timedelta(days=settings.refresh_token_days),
                       user_agent=(request.headers.get("user-agent") or "")[:300]))
    user.last_login_at = utcnow()
    await s.commit()
    return SessionOut(access_token=create_access_token(user.id, org_id or (orgs[0].id if orgs else None), {"av": user.auth_version}), refresh_token=raw,
                      expires_in=settings.access_token_minutes * 60,
                      user=UserOut(id=user.id, email=user.email, name=user.name, is_superuser=user.is_superuser, email_verified=user.email_verified_at is not None, email_verification_required=settings.email_verification_required), orgs=orgs)


@router.post("/register", response_model=SessionOut)
async def register(body: RegisterIn, request: Request, background: BackgroundTasks, s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    n_users = (await s.execute(select(func.count()).select_from(User))).scalar()
    if not settings.allow_registration and n_users > 0:
        raise Forbidden("Registration is closed. Ask an administrator for an invite.")
    email = body.email.lower()
    if (await s.execute(select(User).where(User.email == email))).scalar_one_or_none():
        raise Conflict("An account with this email already exists.")
    user = User(email=email, name=body.name or email.split("@")[0], password_hash=hash_password(body.password), is_superuser=n_users == 0)
    org = Organization(name=body.org_name or f"{user.name}'s workspace", slug=_slug(body.org_name or user.name))
    s.add_all([user, org])
    await s.flush()
    org.max_concurrent = plan(org)["max_concurrent"]
    s.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    await ensure_monthly_grant(s, org)
    audit.record(s, "user.register", org_id=org.id, user_id=user.id, ip=client_ip(request))
    await account_security.issue(s, user, "verify")
    background.add_task(mail.dispatch_pending)
    return await _session(s, user, request, org.id)


@router.post("/login", response_model=SessionOut)
async def login(body: LoginIn, request: Request, s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    await hit(f"auth:{body.email.lower()}", settings.rate_limit_auth_per_minute)
    user = (await s.execute(select(User).where(User.email == body.email.lower()).with_for_update())).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash) or not user.is_active:
        raise Unauthorized("Wrong email or password.")
    audit.record(s, "user.login", user_id=user.id, ip=client_ip(request))
    return await _session(s, user, request)


@router.post("/refresh", response_model=SessionOut)
async def refresh(body: RefreshIn, request: Request, s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    row = (await s.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token)))).scalar_one_or_none()
    # Lock users before their credentials, matching reset/change-password lock order.
    user = (await s.execute(select(User).where(User.id == row.user_id).with_for_update())).scalar_one_or_none() if row else None
    if row:
        await s.refresh(row)
    now = utcnow()
    if not row or row.revoked_at or (row.expires_at.replace(tzinfo=now.tzinfo) if row.expires_at.tzinfo is None else row.expires_at) < now:
        if row and row.revoked_at:   # reuse of a rotated token: revoke the whole family for this user
            for t in (await s.execute(select(RefreshToken).where(and_(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))))).scalars():
                t.revoked_at = now
            await s.commit()
        raise Unauthorized("Session expired. Sign in again.", code="refresh_invalid")
    claimed = (await s.execute(update(RefreshToken).where(RefreshToken.id == row.id,
        RefreshToken.revoked_at.is_(None), RefreshToken.expires_at > now).values(revoked_at=now)
        .returning(RefreshToken.id))).scalar_one_or_none()
    if not claimed:
        raise Unauthorized("Session expired. Sign in again.", code="refresh_invalid")
    if not user or not user.is_active:
        raise Unauthorized("Account disabled.")
    return await _session(s, user, request)


@router.post("/logout")
async def logout(body: RefreshIn, s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(RefreshToken).where(RefreshToken.token_hash == sha256(body.refresh_token)))).scalar_one_or_none()
    if row and not row.revoked_at:
        row.revoked_at = utcnow()
        await s.commit()
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    return {"user": UserOut(id=user.id, email=user.email, name=user.name, is_superuser=user.is_superuser, email_verified=user.email_verified_at is not None, email_verification_required=settings.email_verification_required), "orgs": await _orgs(s, user)}


@router.post("/password")
async def change_password(body: ChangePasswordIn, request: Request, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    await hit(f"auth:{user.email}", settings.rate_limit_auth_per_minute)
    u = (await s.execute(select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True))).scalar_one()
    if not verify_password(body.current_password, u.password_hash):
        raise Unauthorized("Current password is wrong.")
    u.password_hash = hash_password(body.new_password)
    await account_security.revoke_sessions(s, u)
    audit.record(s, "user.password_changed", user_id=user.id)
    await s.commit()
    return {"ok": True}


@router.post("/invites/accept", response_model=SessionOut)
async def accept_invite(body: AcceptInviteIn, request: Request, background: BackgroundTasks, s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    inv = (await s.execute(select(Invite).where(Invite.token_hash == sha256(body.token)).with_for_update())).scalar_one_or_none()
    now = utcnow()
    if not inv or inv.accepted_at or (inv.expires_at.replace(tzinfo=now.tzinfo) if inv.expires_at.tzinfo is None else inv.expires_at) < now:
        raise NotFound("This invite is invalid or has expired.")
    await hit(f"auth:{inv.email}", settings.rate_limit_auth_per_minute)
    user = (await s.execute(select(User).where(User.email == inv.email).with_for_update())).scalar_one_or_none()
    if user is None:
        user = User(email=inv.email, name=body.name or inv.email.split("@")[0], password_hash=hash_password(body.password))
        s.add(user)
        await s.flush()
        await account_security.issue(s, user, "verify")
        background.add_task(mail.dispatch_pending)
    # Inviting admins receive the raw link; it cannot authenticate an existing account.
    elif not verify_password(body.password, user.password_hash) or not user.is_active:
        raise Unauthorized("Wrong password or account disabled.")
    exists = (await s.execute(select(Membership).where(and_(Membership.org_id == inv.org_id, Membership.user_id == user.id)))).scalar_one_or_none()
    if not exists:
        if settings.billing_enabled:
            from app.services.billing import account
            paid = await account(s, inv.org_id, lock=True)
            count = (await s.execute(select(func.count()).select_from(Membership).where(Membership.org_id == inv.org_id))).scalar()
            if count >= paid.seats:
                raise Conflict("This workspace needs another paid seat before accepting this invitation.")
        s.add(Membership(org_id=inv.org_id, user_id=user.id, role=inv.role))
    inv.accepted_at = now
    audit.record(s, "invite.accepted", org_id=inv.org_id, user_id=user.id, target=inv.email, ip=client_ip(request))
    return await _session(s, user, request, inv.org_id)


_GENERIC_EMAIL = {"ok": True, "message": "If this account is eligible, an email will be sent shortly."}


async def _email_request(body, request, background, s, purpose):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    await hit(f"account-email:{body.email}", 3, 3600)
    user = (await s.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if user and user.is_active and (purpose == "reset" or user.email_verified_at is None):
        await account_security.issue(s, user, purpose)
        audit.record(s, f"user.{purpose}_requested", user_id=user.id, ip=client_ip(request))
        await s.commit()
    background.add_task(mail.dispatch_pending)
    return _GENERIC_EMAIL


@router.post("/forgot-password")
async def forgot_password(body: EmailRequestIn, request: Request, background: BackgroundTasks, s: AsyncSession = Depends(get_session)):
    return await _email_request(body, request, background, s, "reset")


@router.post("/verification-email")
async def verification_email(body: EmailRequestIn, request: Request, background: BackgroundTasks, s: AsyncSession = Depends(get_session)):
    return await _email_request(body, request, background, s, "verify")


@router.post("/reset-password")
async def reset_password(body: ResetPasswordIn, request: Request, s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    user = await account_security.consume(s, body.token, "reset")
    user.password_hash = hash_password(body.new_password)
    await account_security.revoke_sessions(s, user)
    audit.record(s, "user.password_reset", user_id=user.id, ip=client_ip(request))
    await s.commit()
    return {"ok": True}


@router.post("/verify-email")
async def verify_email(body: AccountTokenIn, request: Request, s: AsyncSession = Depends(get_session)):
    await hit(f"auth:{client_ip(request)}", settings.rate_limit_auth_per_minute)
    user = await account_security.consume(s, body.token, "verify")
    user.email_verified_at = utcnow()
    audit.record(s, "user.email_verified", user_id=user.id, ip=client_ip(request))
    await s.commit()
    return {"ok": True}
