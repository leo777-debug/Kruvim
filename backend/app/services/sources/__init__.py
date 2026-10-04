"""Traceable public reference data and explicit commercial-use gating."""
import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import case, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.db.base import utcnow
from app.models import DataSource, Signal, SourceObservation

from .catalog import CATALOG


async def ensure_sources(s):
    have = set((await s.execute(select(DataSource.key))).scalars())
    values = []
    for metadata in CATALOG:
        if metadata["key"] not in have:
            values.append({**metadata, "id": hashlib.sha256(metadata["key"].encode()).hexdigest()[:32],
                "created_at": utcnow(), "last_checked_at": datetime(2026, 10, 4, tzinfo=UTC)})
    if values:
        insert = sqlite_insert if s.bind.dialect.name == "sqlite" else pg_insert
        await s.execute(insert(DataSource).values(values).on_conflict_do_nothing(index_elements=["key"]))
    # Existing observations retain original URLs/times. Unknown legacy sources are explicitly placeholders.
    mapping = dict((await s.execute(select(DataSource.key, DataSource.id))).all())
    await s.execute(update(Signal).where(Signal.source_id.is_(None)).values(
        source_id=case(mapping, value=Signal.source, else_=mapping["placeholder_priors"])))


def signal_source(source):
    return {"source_id": source.id, "source_name": source.name, "source_url": source.url, "licence": source.licence,
            "status": source.status, "label": "estimate, source pending" if source.status == "placeholder" else source.name,
            "production_eligible": eligible(source), "source_weight": source.reliability if eligible(source) else 0}


def eligible(source):
    return source.status == "active" and source.licence_approved and source.reliability > 0


def payload(source):
    return {key: getattr(source, key) for key in ("id", "key", "name", "publisher", "country", "geography_level", "url",
        "access_method", "licence", "attribution", "cadence", "reliability", "notes", "last_checked_at", "status", "attributes",
        "terms_url", "licence_approved", "licence_approved_at", "config")} | {"production_eligible": eligible(source)}


async def store_observations(s, source, rows, raw_ref):
    now = utcnow()
    values = []
    for row in rows:
        canonical = json.dumps({"source": source.id, **row}, sort_keys=True, default=str, ensure_ascii=False)
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        values.append({**row, "id": fingerprint[:32], "source_id": source.id, "retrieved_at": now,
                       "raw_ref": raw_ref, "fingerprint": fingerprint})
    count = 0
    insert = sqlite_insert if s.bind.dialect.name == "sqlite" else pg_insert
    for offset in range(0, len(values), 100):
        result = await s.execute(insert(SourceObservation).values(values[offset:offset + 100])
            .on_conflict_do_nothing(index_elements=["fingerprint"]))
        count += max(0, result.rowcount)
    source.last_checked_at = now
    return count
