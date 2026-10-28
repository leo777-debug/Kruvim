"""Model-provider key vault and workspace spending limits.

Keys: workspace admins add, rotate, re-check and delete one key per provider. Every key is validated with a
lightweight authenticated call before it is stored, is encrypted at rest, and only ever comes back masked.
Limits: admins cap the workspace's monthly model calls and spend, and each member's daily calls, on any key."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, principal, role, throttle
from app.core.crypto import decrypt, encrypt
from app.core.errors import AppError, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Organization, ProviderConfig, ProviderKey
from app.services import audit, keyvault, spend
from app.services.llm import PRESETS

router = APIRouter(tags=["model keys and limits"])
ProviderId = Literal[tuple(keyvault.KEY_PROVIDERS)]  # type: ignore[valid-type]


class KeyIn(BaseModel):
    api_key: str = Field(min_length=1, max_length=2000)
    base_url: str = Field(default="", max_length=500)


class LimitsIn(BaseModel):
    monthly_calls: int | None = Field(default=None, ge=1, le=100_000_000)
    monthly_usd: float | None = Field(default=None, gt=0, le=1_000_000)
    member_daily_calls: int | None = Field(default=None, ge=1, le=10_000_000)


def key_out(k: ProviderKey) -> dict:
    return {"provider": k.provider, "label": keyvault.KEY_PROVIDERS[k.provider].label if k.provider in keyvault.KEY_PROVIDERS else k.provider,
            "hint": k.key_hint, "base_url": k.base_url, "status": k.status, "status_message": k.status_message,
            "last_checked_at": k.last_checked_at, "created_at": k.created_at, "rotated_at": k.rotated_at}


async def get_key(s: AsyncSession, org_id: str, provider: str) -> ProviderKey | None:
    return (await s.execute(select(ProviderKey).where(and_(ProviderKey.org_id == org_id, ProviderKey.provider == provider)))).scalar_one_or_none()


async def store_key(s: AsyncSession, p: Principal, provider: str, api_key: str, base_url: str = "") -> ProviderKey:
    """Validate, then create or rotate. A key the provider refuses is never stored."""
    if provider not in keyvault.KEY_PROVIDERS:
        raise AppError(f"Unknown provider '{provider}'.", code="unknown_provider")
    api_key = api_key.strip()
    try:
        check = await keyvault.validate(provider, api_key, base_url.strip())
    except keyvault.KeyRejected as exc:
        raise AppError(str(exc), code="key_rejected")
    if not check.ok:
        raise AppError(check.message + " The key was not saved.", code="key_unverified")
    row = await get_key(s, p.org_id, provider)
    now = utcnow()
    if row is None:
        row = ProviderKey(org_id=p.org_id, provider=provider, created_by=p.user_id)
        s.add(row)
        action = "model_key.add"
    else:
        row.rotated_at = now
        action = "model_key.rotate"
    row.api_key_enc, row.key_hint = encrypt(api_key), keyvault.hint(api_key)
    row.base_url = base_url.strip() or None if keyvault.KEY_PROVIDERS[provider].needs_base_url else None
    row.status, row.status_message, row.last_checked_at = "valid", check.message, now
    audit.record(s, action, org_id=p.org_id, user_id=p.user_id, target=provider, meta={"hint": row.key_hint})
    return row


@router.get("/model-keys")
async def list_keys(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(ProviderKey).where(ProviderKey.org_id == p.org_id))).scalars().all()
    active = (await s.execute(select(ProviderConfig.preset).where(and_(ProviderConfig.org_id == p.org_id,
                                                                       ProviderConfig.is_default.is_(True))))).scalars().first()
    return {"keys": [key_out(k) for k in rows], "providers": keyvault.public_catalog(),
            "active_provider": (PRESETS.get(active) or {}).get("key_provider") if active else None}


@router.put("/model-keys/{provider}", dependencies=[Depends(throttle("expensive", "rate_limit_expensive_per_minute"))])
async def put_key(provider: ProviderId, body: KeyIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    row = await store_key(s, p, provider, body.api_key, body.base_url)
    await s.commit()
    return key_out(row)


@router.post("/model-keys/{provider}/check", dependencies=[Depends(throttle("expensive", "rate_limit_expensive_per_minute"))])
async def check_key(provider: ProviderId, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    row = await get_key(s, p.org_id, provider)
    if not row:
        raise NotFound("No key is saved for that provider.")
    key = decrypt(row.api_key_enc)
    if not key:
        row.status, row.status_message = "invalid", "This key can no longer be read (the server's secret key changed). Add it again."
    else:
        row.key_hint = keyvault.hint(key)          # keys moved from an earlier version had no hint yet
        try:
            check = await keyvault.validate(provider, key, row.base_url or "")
            row.status, row.status_message = ("valid" if check.ok else "unchecked"), check.message
        except keyvault.KeyRejected as exc:
            row.status, row.status_message = "invalid", str(exc)
    row.last_checked_at = utcnow()
    await s.commit()
    return key_out(row)


@router.delete("/model-keys/{provider}")
async def delete_key(provider: ProviderId, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    row = await get_key(s, p.org_id, provider)
    if not row:
        raise NotFound("No key is saved for that provider.")
    await s.delete(row)
    audit.record(s, "model_key.delete", org_id=p.org_id, user_id=p.user_id, target=provider, meta={"hint": row.key_hint})
    await s.commit()
    return {"ok": True}


@router.get("/limits")
async def get_limits(p: Principal = Depends(principal)):
    return {"limits": spend.org_limits(p.org), "used": await spend.usage_now(p.org_id, p.user_id)}


@router.put("/limits")
async def put_limits(body: LimitsIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    org = await s.get(Organization, p.org_id)
    org.settings = {**(org.settings or {}), "limits": body.model_dump()}
    audit.record(s, "limits.update", org_id=p.org_id, user_id=p.user_id, meta=body.model_dump())
    await s.commit()
    return {"limits": spend.org_limits(org), "used": await spend.usage_now(p.org_id, p.user_id)}
