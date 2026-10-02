"""Request authentication and tenancy.

A request is authenticated by either a JWT access token (browser sessions) or an organisation API key
(`Authorization: Bearer krv_...` or `X-API-Key`). The active organisation comes from the API key, the
`X-Org-Id` header, the token's org claim, or the user's first membership - always verified against
memberships. Every query below the API layer is scoped by `principal.org_id`."""
from __future__ import annotations

from dataclasses import dataclass

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Forbidden, NotFound, Unauthorized
from app.core.ratelimit import hit
from app.core.security import API_KEY_PREFIX, decode_access_token, sha256
from app.db.base import utcnow
from app.db.session import get_session
from app.models import ApiKey, Membership, Organization, Project, Simulation, User
from app.models.tenancy import ROLE_RANK


@dataclass
class Principal:
    user: User | None
    org: Organization
    role: str
    via: str              # session | api_key
    api_key_id: str | None = None

    @property
    def org_id(self) -> str:
        return self.org.id

    @property
    def user_id(self) -> str | None:
        return self.user.id if self.user else None

    @property
    def is_superuser(self) -> bool:
        return bool(self.user and self.user.is_superuser)

    def require(self, role: str) -> None:
        if ROLE_RANK.get(self.role, -1) < ROLE_RANK[role]:
            raise Forbidden(f"This action needs the '{role}' role or higher.")


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")) or "unknown"


async def current_user(request: Request, s: AsyncSession = Depends(get_session), authorization: str | None = Header(None)) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthorized("Sign in required.")
    token = authorization.split(" ", 1)[1].strip()
    if token.startswith(API_KEY_PREFIX):
        raise Unauthorized("API keys cannot be used for this endpoint.")
    try:
        data = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise Unauthorized("Session expired.", code="token_expired")
    except jwt.InvalidTokenError:
        raise Unauthorized("Invalid session.")
    user = await s.get(User, data["sub"])
    if not user or not user.is_active:
        raise Unauthorized("Account disabled.")
    request.state.token_org = data.get("org")
    return user


async def principal(request: Request, s: AsyncSession = Depends(get_session), authorization: str | None = Header(None),
                    x_api_key: str | None = Header(None), x_org_id: str | None = Header(None)) -> Principal:
    raw = x_api_key or (authorization.split(" ", 1)[1].strip() if authorization and authorization.lower().startswith("bearer ") else None)
    if raw and raw.startswith(API_KEY_PREFIX):
        key = (await s.execute(select(ApiKey).where(ApiKey.key_hash == sha256(raw)))).scalar_one_or_none()
        if not key or key.revoked_at:
            raise Unauthorized("Invalid API key.")
        org = await s.get(Organization, key.org_id)
        key.last_used_at = utcnow()
        await s.commit()
        p = Principal(None, org, key.role, "api_key", key.id)
    else:
        user = await current_user(request, s, authorization)
        want = x_org_id or getattr(request.state, "token_org", None)
        q = select(Membership).where(Membership.user_id == user.id)
        if want:
            m = (await s.execute(q.where(Membership.org_id == want))).scalar_one_or_none()
            if m is None and not user.is_superuser:
                raise Forbidden("You are not a member of that organisation.")
        else:
            m = (await s.execute(q.order_by(Membership.created_at))).scalars().first()
        if m is None:
            if user.is_superuser and want:
                org = await s.get(Organization, want)
                if not org:
                    raise NotFound("Organisation not found.")
                return Principal(user, org, "owner", "session")
            raise Forbidden("You don't belong to an organisation yet.")
        org = await s.get(Organization, m.org_id)
        p = Principal(user, org, m.role, "session")
    await hit(f"p:{p.api_key_id or p.user_id}", settings.rate_limit_per_minute)
    request.state.principal = p
    return p


def role(min_role: str):
    async def dep(p: Principal = Depends(principal)) -> Principal:
        p.require(min_role)
        return p
    return dep


async def superuser(user: User = Depends(current_user)) -> User:
    if not user.is_superuser:
        raise Forbidden("Platform administrators only.")
    return user


async def get_project(s: AsyncSession, p: Principal, project_id: str) -> Project:
    pr = (await s.execute(select(Project).where(and_(Project.id == project_id, Project.org_id == p.org_id)))).scalar_one_or_none()
    if not pr:
        raise NotFound("Project not found.")
    return pr


async def get_sim(s: AsyncSession, p: Principal, sim_id: str) -> Simulation:
    sim = (await s.execute(select(Simulation).where(and_(Simulation.id == sim_id, Simulation.org_id == p.org_id)))).scalar_one_or_none()
    if not sim:
        raise NotFound("Simulation not found.")
    return sim
