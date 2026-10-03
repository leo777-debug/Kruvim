from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Principal, get_sim, principal, role
from app.core.config import settings
from app.core.errors import AppError, Conflict, NotFound
from app.db.base import utcnow
from app.db.session import get_session
from app.models import Organization, SocialConnection, SocialPost
from app.schemas.creator import AudienceProfileIn, ConsentIn, PostLinkIn
from app.services import accuracy, audit, social
from app.services.creator import PRESETS
from app.services.social_sync import sync_connection

router = APIRouter(tags=["creator analytics"])
Platform = Literal["youtube", "tiktok", "instagram"]


def connection_public(c):
    return {"id": c.id, "platform": c.platform, "account_name": c.account_name, "connected": bool(c.tokens_enc),
            "audience": c.audience, "last_sync_at": c.last_sync_at, "last_error": c.last_error, "share_accuracy": c.share_accuracy}


async def own_connection(s, p, connection_id):
    c = (await s.execute(select(SocialConnection).where(SocialConnection.id == connection_id,
                                                       SocialConnection.org_id == p.org_id))).scalar_one_or_none()
    if not c:
        raise NotFound("Analytics account not found in this workspace.")
    return c


@router.get("/social/connections")
async def connections(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    rows = (await s.execute(select(SocialConnection).where(SocialConnection.org_id == p.org_id))).scalars().all()
    return {"connections": [connection_public(c) for c in rows], "providers": [
        {"platform": k, "configured": all(social.credentials(k)), "limitations": v["limitations"]} for k, v in social.PROVIDERS.items()]}


@router.post("/social/{platform}/connect")
async def connect(platform: Platform, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    if not all(social.credentials(platform)):
        raise AppError("This analytics integration needs application credentials. See the deployment settings.")
    c = (await s.execute(select(SocialConnection).where(SocialConnection.org_id == p.org_id,
                                                       SocialConnection.platform == platform))).scalar_one_or_none()
    if not c:
        c = SocialConnection(org_id=p.org_id, platform=platform)
        s.add(c)
    state = secrets.token_urlsafe(32)
    c.state_hash = hashlib.sha256(state.encode()).hexdigest()
    c.state_expires_at = utcnow() + timedelta(minutes=10)
    audit.record(s, "social.connect.start", org_id=p.org_id, user_id=p.user_id, target=platform)
    try:
        await s.commit()
    except IntegrityError:
        await s.rollback()
        raise Conflict("An account connection is already being created. Retry.")
    return {"url": social.authorize_url(platform, state)}


@router.get("/social/{platform}/callback")
async def callback(platform: Platform, state: str = Query(..., min_length=20, max_length=200),
                   code: str | None = Query(None, max_length=2000), error: str | None = Query(None, max_length=200),
                   s: AsyncSession = Depends(get_session)):
    # A persisted, short-lived one-use state authorizes this callback; no browser session token in URLs.
    digest = hashlib.sha256(state.encode()).hexdigest()
    claim = await s.execute(update(SocialConnection).where(SocialConnection.platform == platform,
        SocialConnection.state_hash == digest, SocialConnection.state_expires_at > utcnow()).values(state_hash=None, state_expires_at=None)
        .returning(SocialConnection.id, SocialConnection.org_id))
    identity = claim.first()
    await s.commit()
    if not identity:
        raise AppError("Analytics authorization expired or was already used. Start connecting again.")
    c = (await s.execute(select(SocialConnection).where(SocialConnection.id == identity.id,
                                                       SocialConnection.org_id == identity.org_id))).scalar_one()
    status = "error"
    if code and not error:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                token = await social.exchange(client, platform, code)
                account_id, account_name = await social.identity(client, platform, token["access_token"])
                if c.account_id and c.account_id != account_id:
                    raise ValueError("Disconnect the previous account before connecting a different one.")
                social.save_tokens(c, token)
                c.account_id, c.account_name = account_id, account_name
                c.next_sync_at, c.last_error = utcnow(), None
                status = "connected"
        except (ValueError, httpx.HTTPError, KeyError, TypeError):
            c.last_error = "Account authorization failed. Check the application permissions or disconnect before switching accounts."
    else:
        c.last_error = "Account authorization was declined."
    audit.record(s, "social.connect." + status, org_id=c.org_id, target=platform)
    await s.commit()
    return RedirectResponse(f"{settings.public_url.rstrip('/')}/my-audience?connection={status}", status_code=303)


@router.delete("/social/connections/{connection_id}")
async def disconnect(connection_id: str, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    c = await own_connection(s, p, connection_id)
    if c.sync_until and c.sync_until > utcnow():
        raise Conflict("An analytics sync is running. Try disconnecting when it finishes.")
    await s.delete(c)
    audit.record(s, "social.disconnect", org_id=p.org_id, user_id=p.user_id, target=c.platform)
    await s.commit()
    return {"ok": True}


@router.patch("/social/connections/{connection_id}/consent")
async def consent(connection_id: str, body: ConsentIn, p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    c = await own_connection(s, p, connection_id)
    c.share_accuracy = body.share_accuracy
    audit.record(s, "social.accuracy_consent", org_id=p.org_id, user_id=p.user_id, target=str(body.share_accuracy))
    await s.commit()
    return connection_public(c)


@router.post("/social/connections/{connection_id}/sync")
async def sync(connection_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    c = await own_connection(s, p, connection_id)
    if not c.tokens_enc:
        raise AppError("Connect this account first.")
    # Manual retries use the same lease as scheduled workers.
    if not await sync_connection(c.id, p.org_id):
        raise Conflict("Analytics are already syncing.")
    await s.refresh(c)
    return connection_public(c)


@router.get("/simulations/{sim_id}/published-posts")
async def posts(sim_id: str, p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    rows = (await s.execute(select(SocialPost).where(SocialPost.simulation_id == sim_id, SocialPost.org_id == p.org_id))).scalars().all()
    return [{"id": c.id, "connection_id": c.connection_id, "variant": c.variant, "post_id": c.post_id,
             "metrics": c.metrics, "synced_at": c.synced_at, "published_at": c.published_at, "last_error": c.last_error} for c in rows]


@router.post("/simulations/{sim_id}/published-posts")
async def link_post(sim_id: str, body: PostLinkIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    sim = await get_sim(s, p, sim_id)
    c = await own_connection(s, p, body.connection_id)
    if sim.status != "completed" or not sim.finished_at or not c.tokens_enc:
        raise AppError("Complete the simulation and connect an analytics account first.")
    if c.platform != sim.content.get("platform"):
        raise AppError("The analytics account must match this simulation's platform.")
    ab = sim.results.get("ab", {})
    score = ab.get(body.variant.lower(), {}).get("score")
    if score is None:
        score = sim.results.get("score", {}).get("first_impression") if body.variant == "A" else None
    if score is None:
        raise AppError("No prediction exists for that variant.")
    row = SocialPost(org_id=p.org_id, connection_id=c.id, simulation_id=sim_id, variant=body.variant,
                     post_id=body.post_id, predicted_score=score, predicted_at=sim.finished_at,
                     prediction={"dry": sim.results.get("provider", {}).get("dry", True), "winner": ab.get("winner", "tie"),
                                 "b_kind": sim.content.get("b_kind", "version"), "niche": sim.niche,
                                 "sources": sorted({x.get("source") for items in sim.results.get("creator", {}).get("agent_signals", {}).values()
                                                    for x in items if x.get("source")})})
    # Validate ownership before persisting a link; the scheduler subsequently needs only the post ID.
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await social.access_token(client, c)
            metrics, published = await social.outcome(client, c, body.post_id, token)
            row.metrics, row.published_at = metrics, published
    except (ValueError, httpx.HTTPError, KeyError, TypeError):
        raise AppError("Post analytics are unavailable. Check the post ID, ownership and permissions, then retry.")
    s.add(row)
    c.next_sync_at = utcnow()
    try:
        await s.commit()
    except IntegrityError:
        await s.rollback()
        raise Conflict("This variant or published post is already linked. Remove its link before changing it.")
    return {"id": row.id, "variant": row.variant, "post_id": row.post_id}


@router.delete("/simulations/{sim_id}/published-posts/{post_id}")
async def unlink_post(sim_id: str, post_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    await get_sim(s, p, sim_id)
    row = (await s.execute(select(SocialPost).where(SocialPost.id == post_id, SocialPost.simulation_id == sim_id,
                                                   SocialPost.org_id == p.org_id))).scalar_one_or_none()
    if not row:
        raise NotFound("Post link not found.")
    c = await own_connection(s, p, row.connection_id)
    if c.sync_until and c.sync_until > utcnow():
        raise Conflict("Analytics are syncing. Try removing the link when the sync finishes.")
    from sqlalchemy import delete

    from app.models import PerformanceReport
    await s.execute(delete(PerformanceReport).where(PerformanceReport.social_post_id == row.id, PerformanceReport.org_id == p.org_id))
    await s.delete(row)
    await s.commit()
    return {"ok": True}


@router.get("/audience-presets")
async def presets(_: Principal = Depends(principal)):
    return PRESETS


@router.get("/my-audience")
async def my_audience(p: Principal = Depends(principal)):
    return {"profile": (p.org.settings or {}).get("creator_audience"), "memory": (p.org.settings or {}).get("creator_memory", {})}


@router.put("/my-audience")
async def save_audience(body: AudienceProfileIn, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(Organization).where(Organization.id == p.org_id).with_for_update())).scalar_one()
    row.settings = {**(row.settings or {}), "creator_audience": {**body.model_dump(), "source": "manual", "updated_at": utcnow().isoformat()}}
    await s.commit()
    return row.settings["creator_audience"]


@router.post("/social/connections/{connection_id}/use-audience")
async def use_audience(connection_id: str, p: Principal = Depends(role("member")), s: AsyncSession = Depends(get_session)):
    c = await own_connection(s, p, connection_id)
    if not any(c.audience.get(k) for k in ("countries", "ages", "genders")):
        raise AppError("This provider has not returned a demographic breakdown. Enter one manually.")
    row = (await s.execute(select(Organization).where(Organization.id == p.org_id).with_for_update())).scalar_one()
    row.settings = {**(row.settings or {}), "creator_audience": {"split": {k: c.audience.get(k, {}) for k in ("countries", "ages", "genders")},
        "label": c.account_name, "source": c.platform, "connection_id": c.id, "kind": c.audience.get("kind"), "updated_at": utcnow().isoformat()}}
    await s.commit()
    return row.settings["creator_audience"]


@router.delete("/my-audience/memory")
async def reset_memory(p: Principal = Depends(role("admin")), s: AsyncSession = Depends(get_session)):
    row = (await s.execute(select(Organization).where(Organization.id == p.org_id).with_for_update())).scalar_one()
    row.settings = {**(row.settings or {}), "creator_memory": {}}
    await s.commit()
    return {"ok": True}


@router.get("/accuracy")
async def workspace_accuracy(p: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    return await accuracy.report(s, p.org_id)


@router.get("/calibration/source-weights")
async def source_weights(niche: str | None = Query(None, max_length=40), _: Principal = Depends(principal), s: AsyncSession = Depends(get_session)):
    from app.services.source_weights import learned_weights
    return await learned_weights(s, niche)


@router.get("/public/accuracy")
async def public_accuracy(request: Request, s: AsyncSession = Depends(get_session)):
    from app.api.deps import client_ip
    from app.core.ratelimit import hit
    await hit(f"public-accuracy:{client_ip(request)}", settings.rate_limit_per_minute)
    # Explicit exception to tenant scoping: opted-in, thresholded aggregates only.
    return await accuracy.report(s)
