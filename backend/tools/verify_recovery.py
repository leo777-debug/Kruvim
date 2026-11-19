"""Read-only recovery evidence. Run against a quiesced source, then an isolated restore.

python -m tools.verify_recovery capture /restricted/recovery.json
python -m tools.verify_recovery verify /restricted/recovery.json
Uses ordinary KRUVIM_* settings. Never restores, deletes, or starts jobs.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import inspect, text

from app.core.config import settings
from app.db.session import engine
from app.services import storage


async def snapshot():
    schema = settings.database_schema if not settings.is_sqlite else None
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names(schema=schema))
        if "alembic_version" not in names:
            raise ValueError("Database has no migration revision; migrate the source before capturing evidence")
        quote = conn.dialect.identifier_preparer.quote
        prefix = quote(schema) + "." if schema else ""
        counts = {}
        for name in sorted(names):
            counts[name] = (await conn.execute(text(f"SELECT count(*) FROM {prefix}{quote(name)}"))).scalar_one()
        revision = (await conn.execute(text(f"SELECT version_num FROM {prefix}alembic_version"))).scalars().all()
        if not revision:
            raise ValueError("Database migration revision is empty")
        assets = (await conn.execute(text(f"SELECT id, storage_key, size, text_excerpt FROM {prefix}assets ORDER BY id"))).all()
    files = {}
    database_assets = {}
    for asset_id, key, expected_size, excerpt in assets:
        if not key:
            database_assets[asset_id] = {"size": expected_size,
                                         "sha256": hashlib.sha256((excerpt or "").encode()).hexdigest()}
            continue
        raw = await storage.get(key)
        if len(raw) != expected_size:
            raise ValueError("An uploaded file differs from its database size")
        files[asset_id] = {"key": key, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    return {"format": 1, "revision": sorted(revision), "tables": counts, "assets": files,
            "database_assets": database_assets}


def compare(expected, actual):
    if expected.get("format") != 1:
        raise ValueError("Unsupported evidence format")
    mismatches = [field for field in ("revision", "tables", "assets", "database_assets") if expected[field] != actual[field]]
    if mismatches:
        raise ValueError("Recovery mismatch: " + ", ".join(mismatches))


async def run(args):
    try:
        actual = await snapshot()
        if not actual["assets"] and not args.allow_empty_assets:
            raise ValueError("No uploaded files checked; add a fixture or explicitly use --allow-empty-assets")
        if args.mode == "capture":
            actual["captured_at"] = datetime.now(UTC).isoformat()
            # Evidence contains private object keys. Refuse replacement and restrict creation permissions.
            fd = os.open(args.manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(actual, output, indent=2)
        else:
            compare(json.loads(Path(args.manifest).read_text(encoding="utf-8")), actual)
        print(json.dumps({"status": "passed", "mode": args.mode,
                          "tables": len(actual["tables"]), "files": len(actual["assets"])}))
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("capture", "verify"))
    parser.add_argument("manifest")
    parser.add_argument("--allow-empty-assets", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        # Provider/DB exceptions may contain credentials, URLs or private keys: do not print them.
        message = str(exc) if isinstance(exc, (ValueError, FileExistsError)) else type(exc).__name__
        if isinstance(exc, FileExistsError):
            message = "Evidence file already exists"
        print(json.dumps({"status": "failed", "reason": message}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
