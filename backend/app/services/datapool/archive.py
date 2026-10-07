"""Compress old public snapshots to configured S3-compatible storage and restore on demand."""
import gzip
import json
from datetime import timedelta

from sqlalchemy import select

from app.core.config import settings
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import RegionSnapshot
from app.services import storage


async def load(row):
    if row.archive_key:
        return json.loads(gzip.decompress(await storage.get(row.archive_key)))
    return row.data


async def compress_old():
    if settings.storage_backend != "s3" or not settings.s3_bucket:
        return 0
    async with session_scope() as s:
        rows = (await s.execute(select(RegionSnapshot).where(RegionSnapshot.hour < utcnow() - timedelta(days=settings.snapshot_archive_days),
            RegionSnapshot.archive_key.is_(None)).order_by(RegionSnapshot.hour).limit(100))).scalars().all()
        for row in rows:
            key = f"snapshots/{row.region}/{row.hour:%Y/%m/%d/%H}.json.gz"
            payload = gzip.compress(json.dumps(row.data, ensure_ascii=False).encode(), mtime=0)
            await storage.put(key, payload)  # never clear DB contents before upload succeeds
            row.archive_key, row.data = key, {}
        return len(rows)
