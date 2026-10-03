from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, current_user, principal, role
from app.api.routes.auth import _slug
from app.core.config import settings
from app.core.crypto import encrypt, mask
from app.core.errors import Conflict, Forbidden, NotFound, QuotaExceeded
from app.core.security import new_api_key, new_invite_token
from app.db.base import utcnow
from app.db.session import get_session
from app.models import ApiKey, AuditLog, CreditLedger, Invite, Membership, Organization, ProviderConfig, UsageEvent, User
from app.models.tenancy import ROLE_RANK
from app.schemas.workspace import ApiKeyIn, InviteIn, MemberUpdate, OrgCreate, OrgUpdate, ProviderIn
from app.services import audit
from app.services.llm import PRESETS, ProviderSettings, Usage, make_llm
from app.services.providers import resolve, to_settings
from app.services.quotas import PLANS, ensure_monthly_grant, plan

router = APIRouter(tags=["workspace"])


def _org(o: Organization, role_: str | None = None) -> dict:
    return {"id": o.id, "name": o.name, "slug": o.slug, "plan": o.plan, "plan_limits": plan(o), "credits_balance": o.credits_balance,
            "max_concurrent": o.max_concurrent, "role": role_, "created_at": o.created_at}


@router.post("/orgs")
async def create_org(body: OrgCreate, user: User = Depends(current_user), s: AsyncSession = Depends(get_session)):
    org = Organization(name=body.name, slug=_slug(body.name))
    s.add(org)
    await s.flush()
    s.add(Membership(org_id=org.id, user_id=user.id, role="owner"))
    await ensure_monthly_grant(s, org)
    audit.record(s, "org.create", org_id=org.id, user_id=user.id)
    await s.commit()
    return _org(org, "owner")


@router.get("/orgs/current")
async def current_org(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    members = (await s.execute(select(func.count()).select_from(Membership).where(Membership.org_id == p.org_id))).scalar()
    return {**_org(p.org, p.role), "members": members}


@router.patch("/orgs/current")
async def update_org(body: OrgUpdate, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    org = await s.get(Organization, p.org_id)
    if body.name:
        org.name = body.name
    audit.record(s, "org.update", org_id=org.id, user_id=p.user_id, meta=body.model_dump(exclude_none=True))
    await s.commit()
    return _org(org, p.role)


# ---- members & invites ------------------------------------------------------------------------------------
@router.get("/members")
async def members(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.org_id == p.org_id)
                            .order_by(Membership.created_at))).all()
    invites = (await s.execute(select(Invite).where(and_(Invite.org_id == p.org_id, Invite.accepted_at.is_(None))))).scalars().all()
    return {"members": [{"id": m.id, "user_id": u.id, "email": u.email, "name": u.name, "role": m.role, "joined_at": m.created_at,
                         "last_login_at": u.last_login_at} for m, u in rows],
            "invites": [{"id": i.id, "email": i.email, "role": i.role, "expires_at": i.expires_at} for i in invites]}


@router.post("/members/invites")
async def invite(body: InviteIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    if ROLE_RANK[body.role] > ROLE_RANK[p.role]:
        raise Forbidden("You cannot invite someone with a higher role than yours.")
    count = (await s.execute(select(func.count()).select_from(Membership).where(Membership.org_id == p.org_id))).scalar()
    if count >= plan(p.org)["max_members"]:
        raise QuotaExceeded(f"Your plan allows {plan(p.org)['max_members']} members.")
    raw, hashed = new_invite_token()
    inv = Invite(org_id=p.org_id, email=body.email.lower(), role=body.role, token_hash=hashed, invited_by=p.user_id,
                 expires_at=utcnow() + timedelta(days=7))
    s.add(inv)
    audit.record(s, "member.invite", org_id=p.org_id, user_id=p.user_id, target=inv.email, meta={"role": body.role})
    await s.commit()
    # Email delivery is deployment-specific; the link is returned so an admin can share it.
    return {"id": inv.id, "email": inv.email, "role": inv.role, "expires_at": inv.expires_at,
            "accept_url": f"{settings.public_url}/invite/{raw}"}


@router.delete("/members/invites/{invite_id}")
async def revoke_invite(invite_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    inv = (await s.execute(select(Invite).where(and_(Invite.id == invite_id, Invite.org_id == p.org_id)))).scalar_one_or_none()
    if not inv:
        raise NotFound("Invite not found.")
    await s.delete(inv)
    await s.commit()
    return {"ok": True}


@router.patch("/members/{member_id}")
async def update_member(member_id: str, body: MemberUpdate, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    m = (await s.execute(select(Membership).where(and_(Membership.id == member_id, Membership.org_id == p.org_id)))).scalar_one_or_none()
    if not m:
        raise NotFound("Member not found.")
    if ROLE_RANK[body.role] > ROLE_RANK[p.role] or ROLE_RANK[m.role] > ROLE_RANK[p.role]:
        raise Forbidden("You cannot change a role above your own.")
    if m.role == "owner" and body.role != "owner":
        owners = (await s.execute(select(func.count()).select_from(Membership).where(and_(Membership.org_id == p.org_id, Membership.role == "owner")))).scalar()
        if owners <= 1:
            raise Conflict("An organisation needs at least one owner.")
    m.role = body.role
    audit.record(s, "member.role", org_id=p.org_id, user_id=p.user_id, target=m.user_id, meta={"role": body.role})
    await s.commit()
    return {"ok": True}


@router.delete("/members/{member_id}")
async def remove_member(member_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    m = (await s.execute(select(Membership).where(and_(Membership.id == member_id, Membership.org_id == p.org_id)))).scalar_one_or_none()
    if not m:
        raise NotFound("Member not found.")
    if m.role == "owner":
        raise Conflict("Transfer ownership before removing an owner.")
    await s.delete(m)
    audit.record(s, "member.remove", org_id=p.org_id, user_id=p.user_id, target=m.user_id)
    await s.commit()
    return {"ok": True}


# ---- API keys -------------------------------------------------------------------------------------------------
@router.get("/api-keys")
async def list_keys(p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(ApiKey).where(ApiKey.org_id == p.org_id).order_by(desc(ApiKey.created_at)))).scalars().all()
    return [{"id": k.id, "name": k.name, "prefix": k.prefix, "role": k.role, "created_at": k.created_at, "last_used_at": k.last_used_at,
             "revoked": bool(k.revoked_at)} for k in rows]


@router.post("/api-keys")
async def create_key(body: ApiKeyIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    k = new_api_key()
    row = ApiKey(org_id=p.org_id, name=body.name, prefix=k.prefix, key_hash=k.hashed, role=body.role, created_by=p.user_id)
    s.add(row)
    audit.record(s, "api_key.create", org_id=p.org_id, user_id=p.user_id, target=k.prefix)
    await s.commit()
    return {"id": row.id, "name": row.name, "prefix": k.prefix, "role": row.role, "key": k.raw,
            "note": "Copy this key now; it will not be shown again."}


@router.delete("/api-keys/{key_id}")
async def revoke_key(key_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    k = (await s.execute(select(ApiKey).where(and_(ApiKey.id == key_id, ApiKey.org_id == p.org_id)))).scalar_one_or_none()
    if not k:
        raise NotFound("API key not found.")
    k.revoked_at = utcnow()
    audit.record(s, "api_key.revoke", org_id=p.org_id, user_id=p.user_id, target=k.prefix)
    await s.commit()
    return {"ok": True}


# ---- model providers ------------------------------------------------------------------------------------------
def _provider_out(c: ProviderConfig) -> dict:
    from app.core.crypto import decrypt
    return {"id": c.id, "name": c.name, "preset": c.preset, "provider": c.provider, "base_url": c.base_url, "api_key_set": bool(c.api_key_enc),
            "api_key_hint": mask(decrypt(c.api_key_enc)), "voice_model": c.voice_model, "report_model": c.report_model,
            "vision_model": c.vision_model, "concurrency": c.concurrency, "temperature": c.temperature, "json_mode": c.json_mode,
            "price_in": c.price_in, "price_cached": c.price_cached, "price_out": c.price_out, "is_default": c.is_default,
            "scope": "platform" if c.org_id is None else "org"}


@router.get("/providers")
async def providers(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(ProviderConfig).where(ProviderConfig.org_id == p.org_id).order_by(desc(ProviderConfig.created_at)))).scalars().all()
    res = await resolve(s, p.org_id)
    return {"configs": [_provider_out(c) for c in rows], "presets": PRESETS,
            "active": {"source": res.source, "provider": res.settings.provider, "preset": res.settings.preset,
                       "voice_model": res.settings.voice_model, "report_model": res.settings.report_model, "metered": res.metered}}


async def _upsert_provider(s: AsyncSession, org_id: str | None, body: ProviderIn) -> ProviderConfig:
    preset = PRESETS.get(body.preset)
    if not preset:
        raise Conflict(f"Unknown preset '{body.preset}'.")
    c = (await s.execute(select(ProviderConfig).where(and_(ProviderConfig.org_id.is_(None) if org_id is None else ProviderConfig.org_id == org_id,
                                                           ProviderConfig.is_default.is_(True))))).scalars().first()
    if c is None:
        c = ProviderConfig(org_id=org_id, is_default=True)
        s.add(c)
    data = body.model_dump()
    api_key = data.pop("api_key")
    for k, v in data.items():
        setattr(c, k, v)
    c.provider = preset["provider"]
    if api_key is not None:
        c.api_key_enc = encrypt(api_key) if api_key else None
    return c


@router.put("/providers")
async def save_provider(body: ProviderIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    c = await _upsert_provider(s, p.org_id, body)
    audit.record(s, "provider.save", org_id=p.org_id, user_id=p.user_id, meta={"preset": body.preset})
    await s.commit()
    return _provider_out(c)


@router.delete("/providers")
async def clear_provider(p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    for c in (await s.execute(select(ProviderConfig).where(ProviderConfig.org_id == p.org_id))).scalars():
        await s.delete(c)
    audit.record(s, "provider.clear", org_id=p.org_id, user_id=p.user_id)
    await s.commit()
    return {"ok": True}


def _settings_from(body: ProviderIn, existing: ProviderConfig | None) -> ProviderSettings:
    from app.core.crypto import decrypt
    preset = PRESETS.get(body.preset, PRESETS["custom"])
    key = body.api_key if body.api_key is not None else (decrypt(existing.api_key_enc) if existing else "")
    return ProviderSettings(provider=preset["provider"], preset=body.preset, base_url=body.base_url, api_key=key or "",
                            voice_model=body.voice_model, report_model=body.report_model, vision_model=body.vision_model,
                            concurrency=body.concurrency, temperature=body.temperature, json_mode=body.json_mode, timeout=60)


@router.post("/providers/test")
async def test_provider(body: ProviderIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    existing = (await s.execute(select(ProviderConfig).where(ProviderConfig.org_id == p.org_id))).scalars().first()
    llm = None
    try:
        llm = make_llm(_settings_from(body, existing))
        if llm.is_dry:
            return {"ok": True, "message": "Dry run needs no model. Output is formula-driven and labelled [dry run]."}
        u = Usage()
        import time
        t0 = time.time()
        out = await llm.complete_json(system='Reply with exactly this JSON: {"ok": true, "word": "<one random word>"}', user="Test.",
                                      role="voice", max_tokens=60, usage=u)
        return {"ok": True, "message": f"Model replied in {time.time() - t0:.1f}s: {str(out)[:120]}", "usage": u.as_dict()}
    except Exception as exc:
        return {"ok": False, "message": str(exc)[:500]}
    finally:
        if llm:
            await llm.aclose()


@router.post("/providers/models")
async def provider_models(body: ProviderIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    existing = (await s.execute(select(ProviderConfig).where(ProviderConfig.org_id == p.org_id))).scalars().first()
    llm = None
    try:
        llm = make_llm(_settings_from(body, existing))
        return {"models": await llm.list_models()}
    except Exception as exc:
        return {"models": [], "error": str(exc)[:300]}
    finally:
        if llm:
            await llm.aclose()


# ---- usage & audit ------------------------------------------------------------------------------------------
@router.get("/usage")
async def usage(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await ensure_monthly_grant(s, p.org)
    await s.commit()
    month = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_kind = (await s.execute(select(UsageEvent.kind, func.sum(UsageEvent.quantity), func.sum(UsageEvent.input_tokens),
                                      func.sum(UsageEvent.output_tokens), func.sum(UsageEvent.cost_usd))
                               .where(and_(UsageEvent.org_id == p.org_id, UsageEvent.created_at >= month)).group_by(UsageEvent.kind))).all()
    ledger = (await s.execute(select(CreditLedger).where(CreditLedger.org_id == p.org_id).order_by(desc(CreditLedger.created_at)).limit(50))).scalars().all()
    org = await s.get(Organization, p.org_id)
    res = await resolve(s, p.org_id)
    return {"plan": org.plan, "plans": PLANS, "limits": plan(org), "credits_balance": org.credits_balance, "metered": res.metered,
            "provider_source": res.source,
            "month": [{"kind": k, "calls": int(q or 0), "input_tokens": int(i or 0), "output_tokens": int(o or 0), "cost_usd": c} for k, q, i, o, c in by_kind],
            "ledger": [{"delta": x.delta, "balance_after": x.balance_after, "reason": x.reason, "ref": x.ref, "at": x.created_at} for x in ledger],
            "payment": {"enabled": False, "note": "Credit purchases are not enabled yet."}}


@router.get("/audit")
async def audit_log(p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session), limit: int = 100):
    rows = (await s.execute(select(AuditLog, User.email).outerjoin(User, User.id == AuditLog.user_id).where(AuditLog.org_id == p.org_id)
                            .order_by(desc(AuditLog.created_at)).limit(min(limit, 500)))).all()
    return [{"action": a.action, "target": a.target, "meta": a.meta, "user": email, "ip": a.ip, "at": a.created_at} for a, email in rows]


__all__ = ["router", "to_settings"]
