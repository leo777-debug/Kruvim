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
from app.models import Connector, DataSource, Signal, SignalEmbedding
from app.services.population.regions import CONTEXT_REGIONS

from .base import UA, MissingCredentials, SignalItem
from .connectors import REGISTRY

log = logging.getLogger("kruvim.datapool")
MEASUREMENT_KINDS = {"weather", "tone", "economy"}
ENV_SECRETS = {"reddit_client_id", "reddit_client_secret", "youtube_api_key", "x_bearer_token", "bluesky_handle", "bluesky_app_password", "open_meteo_api_key"}


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
        from app.services.sources import ensure_sources
        await ensure_sources(s)
        have = {c.key for c in (await s.execute(select(Connector).where(Connector.org_id.is_(None)))).scalars()}
        for key, c in REGISTRY.items():
            if key not in have:
                s.add(Connector(org_id=None, key=key, enabled=True, interval_minutes=c.spec.interval_minutes or 0))


async def store_signals(source: str, items: list[SignalItem], org_id=None, simulation_id=None) -> int:
    from .safety import safe_title
    items = [i for i in items if safe_title(i.title, i.payload.get("categories", []))]
    if not items:
        return 0
    now = utcnow()
    async with session_scope() as s:
        from app.services.sources import ensure_sources, signal_source
        await ensure_sources(s)
        sources = {r.key: r for r in (await s.execute(select(DataSource))).scalars()}
        recent = set()
        texty = [i for i in items if i.kind not in MEASUREMENT_KINDS]
        if texty:
            keys = {i.payload.get("source_key", source) for i in items}
            rows = (await s.execute(select(Signal.source, Signal.region, Signal.title).where(
                and_(Signal.source.in_(keys), Signal.org_id == org_id, Signal.simulation_id == simulation_id,
                     Signal.fetched_at >= now - timedelta(hours=24))))).all()
            recent = set(rows)
        n = 0
        for i in items:
            key = i.payload.get("source_key", source)
            if i.kind not in MEASUREMENT_KINDS and (key, i.region, i.title) in recent:
                continue
            recent.add((key, i.region, i.title))
            registered = sources.get(i.payload.get("source_key", source), sources["placeholder_priors"])
            metadata = signal_source(registered)
            if source == "google_news" and registered.status == "placeholder":
                continue  # An unregistered publisher is not licensed by approving an RSS aggregator.
            if settings.env == "production" and not metadata["production_eligible"] and registered.status != "placeholder":
                continue
            signal = Signal(source=i.payload.get("source_key", source), source_id=registered.id, kind=i.kind, region=i.region,
                            title=i.title[:2000], value=i.value, url=(i.url or "")[:1000] or None,
                            lang=i.lang, observed_at=i.observed_at or now, fetched_at=now, payload={**i.payload, "provenance": metadata},
                            org_id=org_id, simulation_id=simulation_id)
            s.add(signal)
            await s.flush()
            from .retrieval import embed
            s.add(SignalEmbedding(id=f"local:{signal.id}", org_id=org_id, signal_id=signal.id, model="local-hash-v1",
                                  vector=embed(signal.title + " " + str(i.payload.get("summary", ""))).tolist()))
            n += 1
        return n


async def run_connector(key: str, regions: list[str] | None = None) -> dict:
    from .limits import source_slot
    async with source_slot(key) as available:
        if not available:
            return {"key": key, "status": "busy", "items": 0}
        return await _run_connector(key, regions)


async def _run_connector(key: str, regions: list[str] | None = None) -> dict:
    conn = REGISTRY[key]
    regs = [r for r in CONTEXT_REGIONS if not regions or r["code"] in regions]
    if key == "open_meteo" and any(r["code"].startswith("AE-") for r in regs):
        regs = [r for r in regs if r["code"] != "AE"]
    async with session_scope() as s:
        row = (await s.execute(select(Connector).where(Connector.org_id.is_(None), Connector.key == key))).scalar_one_or_none()
        cfg = dict(row.config) if row else {}
        secrets = secrets_of(row)
        from app.services.sources import eligible, ensure_sources
        await ensure_sources(s)
        source = (await s.execute(select(DataSource).where(DataSource.key == key))).scalar_one_or_none()
        if settings.env == "production" and key != "publisher_rss" and (not source or not eligible(source)):
            if row:
                row.last_run_at, row.last_status, row.last_error = utcnow(), "skipped", "Source awaits commercial reuse approval in Sources"
            return {"key": key, "status": "skipped", "items": 0, "error": "Source awaits commercial reuse approval"}
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
        if settings.redis_url:
            from app.services.jobs import _arq_pool
            pool = await _arq_pool()
            await pool.enqueue_job("run_connector", key=key, _queue_name="kruvim:connectors",
                                   _job_id=f"connector:{key}:{int(now.timestamp()) // 600}")
            results.append({"key": key, "status": "queued"})
        else:
            results.append(await run_connector(key))
    return results


def _aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
