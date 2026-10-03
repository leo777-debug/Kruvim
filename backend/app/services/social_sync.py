"""Idempotent outcome calibration with a database lease shared by API and workers."""
from datetime import timedelta

import httpx
from sqlalchemy import or_, select, update

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Organization, PerformanceReport, SocialConnection, SocialPost
from app.services import social


async def sync_connection(connection_id: str, org_id: str) -> bool:
    now = utcnow()
    async with session_scope() as s:
        claim = await s.execute(update(SocialConnection).where(
            SocialConnection.id == connection_id, SocialConnection.org_id == org_id, SocialConnection.tokens_enc.is_not(None),
            or_(SocialConnection.sync_until.is_(None), SocialConnection.sync_until < now)
        ).values(sync_until=now + timedelta(minutes=15)))
        if not claim.rowcount:
            return False
    try:
        async with session_scope() as s:
            row = (await s.execute(select(SocialConnection).where(SocialConnection.id == connection_id,
                                                                 SocialConnection.org_id == org_id))).scalar_one()
            async with httpx.AsyncClient(timeout=20) as client:
                token = await social.access_token(client, row)
                row.audience = await social.audience(client, row, token)
                posts = (await s.execute(select(SocialPost).where(SocialPost.connection_id == row.id,
                    SocialPost.org_id == org_id, SocialPost.metrics["finalized"].as_boolean().is_not(True))
                    .order_by(SocialPost.synced_at.asc()).limit(5))).scalars().all()
                real_updates = []
                for post in posts:
                    # Keep the first seven-day snapshot immutable, including its observation time.
                    if post.metrics.get("window_eligible"):
                        continue
                    try:
                        metrics, published = await social.outcome(client, row, post.post_id, token)
                        observed = utcnow()
                        age = (observed - published).total_seconds() / 86400 if published else -1
                        metrics["window_eligible"] = 7 <= age < 8 and post.predicted_at < published
                        metrics["finalized"] = age >= 7
                        metrics["age_days"] = round(age, 3)
                        post.metrics, post.published_at, post.synced_at, post.last_error = metrics, published, observed, None
                        pr = (await s.execute(select(PerformanceReport).where(PerformanceReport.social_post_id == post.id,
                                                                            PerformanceReport.org_id == org_id))).scalar_one_or_none()
                        if pr is None:
                            pr = PerformanceReport(org_id=org_id, simulation_id=post.simulation_id, social_post_id=post.id,
                                                   platform=row.platform, variant=post.variant)
                            s.add(pr)
                        for key in ("views", "likes", "shares", "comments", "retention", "engagement_rate"):
                            setattr(pr, key, metrics.get(key))
                        pr.notes = "Automatically synced from official analytics; unavailable metrics are omitted."
                        real_updates.append({"post_id": post.id, "simulation_id": post.simulation_id, "variant": post.variant,
                                             "platform": row.platform, "metrics": metrics})
                    except (ValueError, httpx.HTTPError, KeyError, TypeError):
                        post.last_error = "Post analytics unavailable. Check ownership, permissions or retry later."
                row.last_sync_at, row.last_error = utcnow(), None
                row.next_sync_at = utcnow() + timedelta(minutes=settings.social_sync_minutes)
                org = (await s.execute(select(Organization).where(Organization.id == org_id).with_for_update())).scalar_one()
                profile = (org.settings or {}).get("creator_audience", {})
                if profile.get("connection_id") == row.id and any(row.audience.get(k) for k in ("countries", "ages", "genders")):
                    org.settings = {**(org.settings or {}), "creator_audience": {**profile,
                        "split": {k: row.audience.get(k, {}) for k in ("countries", "ages", "genders")},
                        "kind": row.audience.get("kind"), "updated_at": utcnow().isoformat()}}
                if real_updates:
                    memory = dict((org.settings or {}).get("creator_memory", {}))
                    actual = {item["post_id"]: item for item in memory.get("actual_outcomes", [])}
                    actual.update({item["post_id"]: item for item in real_updates})
                    memory["actual_outcomes"] = list(actual.values())[-20:]
                    memory["real_summary"] = "Real outcomes: " + "; ".join(f"{item['platform']} variant {item['variant']}: "
                        f"{item['metrics'].get('views')} views, engagement {item['metrics'].get('engagement_rate')}%, retention {item['metrics'].get('retention')}%"
                        for item in memory["actual_outcomes"][-5:])
                    org.settings = {**(org.settings or {}), "creator_memory": memory}
    except (ValueError, httpx.HTTPError, KeyError, TypeError):
        async with session_scope() as s:
            await s.execute(update(SocialConnection).where(SocialConnection.id == connection_id, SocialConnection.org_id == org_id)
                            .values(last_error="Analytics sync failed. Check permissions or reconnect.",
                                    next_sync_at=utcnow() + timedelta(minutes=settings.social_sync_minutes)))
    finally:
        async with session_scope() as s:
            await s.execute(update(SocialConnection).where(SocialConnection.id == connection_id, SocialConnection.org_id == org_id)
                            .values(sync_until=None))
    return True


async def sync_due():
    async with session_scope() as s:
        due = (await s.execute(select(SocialConnection.id, SocialConnection.org_id).where(
            SocialConnection.tokens_enc.is_not(None), or_(SocialConnection.next_sync_at.is_(None), SocialConnection.next_sync_at <= utcnow()))
            .limit(100))).all()
    for cid, oid in due:
        await sync_connection(cid, oid)
