"""Running connectors and persisting their signals."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, timedelta

import httpx
from sqlalchemy import and_, select

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.core.metrics import CONNECTOR_RUNS
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import Connector, Signal
from app.services.population.regions import REGIONS

from .base import UA, MissingCredentials, SignalItem
from .connectors import REGISTRY

log = logging.getLogger("kruvim.datapool")
MEASUREMENT_KINDS = {"weather", "tone", "economy"}
ENV_SECRETS = {"reddit_client_id", "reddit_client_secret", "youtube_api_key", "x_bearer_token", "bluesky_handle", "bluesky_app_password"}


def env_secrets() -> dict:
    return {k: getattr(settings, k) for k in ENV_SECRETS if getattr(settings, k, "")}


def secrets_of(row: Connector | None) -> dict:
    out = env_secrets()
    if row is not None and row.secrets_enc:
        try:
            out.update({k: v for k, v in json.loads(decrypt(row.secrets_enc) or "{}").items() if v})
        except ValueError:
            pass
    return out


def set_secrets(row: Connector, new: dict) -> None:
    cur = {}
    if row.secrets_enc:
        try:
            cur = json.loads(decrypt(row.secrets_enc) or "{}")
        except ValueError:
            cur = {}
    for k, v in new.items():
        if v is None:
            continue
        if v == "":
            cur.pop(k, None)
        else:
            cur[k] = v
    row.secrets_enc = encrypt(json.dumps(cur)) if cur else None


async def ensure_platform_connectors() -> None:
    async with session_scope() as s:
        have = {c.key for c in (await s.execute(select(Connector).where(Connector.org_id.is_(None)))).scalars()}
        for key, c in REGISTRY.items():
            if key not in have:
                s.add(Connector(org_id=None, key=key, enabled=True, interval_minutes=c.spec.interval_minutes or 0))


async def store_signals(source: str, items: list[SignalItem]) -> int:
    if not items:
        return 0
    now = utcnow()
    async with session_scope() as s:
        recent = set()
        texty = [i for i in items if i.kind not in MEASUREMENT_KINDS]
        if texty:
            rows = (await s.execute(select(Signal.region, Signal.title).where(
                and_(Signal.source == source, Signal.fetched_at >= now - timedelta(hours=24))))).all()
            recent = {(r, t) for r, t in rows}
        n = 0
        for i in items:
            if i.kind not in MEASUREMENT_KINDS and (i.region, i.title) in recent:
                continue
            recent.add((i.region, i.title))
            s.add(Signal(source=source, kind=i.kind, region=i.region, title=i.title[:2000], value=i.value, url=(i.url or "")[:1000] or None,
                         lang=i.lang, observed_at=i.observed_at or now, fetched_at=now, payload=i.payload))
            n += 1
        return n


async def run_connector(key: str, regions: list[str] | None = None) -> dict:
    conn = REGISTRY[key]
    regs = [r for r in REGIONS if not regions or r["code"] in regions]
    async with session_scope() as s:
        row = (await s.execute(select(Connector).where(Connector.org_id.is_(None), Connector.key == key))).scalar_one_or_none()
        cfg = dict(row.config) if row else {}
        secrets = secrets_of(row)
    status, err, n = "ok", None, 0
    try:
        async with httpx.AsyncClient(headers=UA, timeout=15, follow_redirects=True) as client:
            items = await asyncio.wait_for(conn.fetch(client, regs, secrets, cfg), timeout=120)
        n = await store_signals(key, items)
        CONNECTOR_RUNS.labels(key, "ok").inc()
    except MissingCredentials as exc:
        status, err = "skipped", str(exc)
        CONNECTOR_RUNS.labels(key, "skipped").inc()
    except Exception as exc:  # network, schema change, quota
        status, err = "error", f"{exc.__class__.__name__}: {str(exc)[:300]}"
        CONNECTOR_RUNS.labels(key, "error").inc()
        log.warning("connector failed", extra={"job": key, "status": err})
    async with session_scope() as s:
        row = (await s.execute(select(Connector).where(Connector.org_id.is_(None), Connector.key == key))).scalar_one_or_none()
        if row:
            row.last_run_at = utcnow()
            row.last_status = status
            row.last_error = err
            row.last_items = n
            row.total_items = (row.total_items or 0) + n
    return {"key": key, "status": status, "items": n, "error": err}


async def run_due() -> list[dict]:
    """Scheduler tick: run every enabled platform connector whose interval has elapsed."""
    await ensure_platform_connectors()
    async with session_scope() as s:
        rows = (await s.execute(select(Connector).where(Connector.org_id.is_(None), Connector.enabled.is_(True)))).scalars().all()
        now = utcnow()
        due = [r.key for r in rows if r.interval_minutes and (r.last_run_at is None or
               _aware(r.last_run_at) + timedelta(minutes=r.interval_minutes) <= now)]
    results = []
    for key in due:   # sequential: polite to free sources
        results.append(await run_connector(key))
    return results


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
