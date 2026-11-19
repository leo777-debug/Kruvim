"""Rehearse migrations and old/new app login on a disposable database only.

python -m tools.verify_release_rollback --baseline-backend /checkout/of/previous/backend
Never uses an inherited DB, Redis, SMTP, storage or model connection.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-backend", type=Path, required=True)
    args = parser.parse_args()
    current = Path(__file__).resolve().parents[1]
    baseline = args.baseline_backend.resolve()
    if not (baseline / "app/main.py").is_file() or baseline == current:
        raise ValueError("Supply a separate checkout of the previous release")
    with tempfile.TemporaryDirectory(prefix="kruvim-release-rollback-") as scratch:
        db = Path(scratch) / "fixture.db"
        env = {k: v for k, v in os.environ.items() if not k.startswith(("KRUVIM_", "VERCEL", "POSTGRES_", "SUPABASE_"))}
        env.update(KRUVIM_ENV="test", KRUVIM_DATABASE_URL="sqlite+aiosqlite:///" + db.as_posix(),
                   KRUVIM_DATABASE_SCHEMA="", KRUVIM_DATA_DIR=scratch, KRUVIM_REDIS_URL="", KRUVIM_SERVERLESS="false",
                   KRUVIM_STORAGE_BACKEND="local", KRUVIM_MAIL_BACKEND="console", KRUVIM_REQUIRE_EMAIL_VERIFICATION="false",
                   KRUVIM_BILLING_ENABLED="false", KRUVIM_LLM_PROVIDER="dryrun", KRUVIM_LLM_PRESET="dryrun",
                   KRUVIM_LLM_API_KEY="", KRUVIM_FIRST_SUPERUSER_EMAIL="", KRUVIM_FIRST_SUPERUSER_PASSWORD="",
                   KRUVIM_POPULATION_SIZE="40000", KRUVIM_SECRET_KEY="local-rollback-test-secret-never-used-in-production")

        def run(module, *argv, cwd=current):
            result = subprocess.run([sys.executable, "-m", module, *argv], cwd=cwd, env=env,
                                    capture_output=True, text=True, timeout=180)
            if result.returncode:
                raise RuntimeError(result.stdout + result.stderr)

        def schema():
            with closing(sqlite3.connect(db)) as connection:
                # SQLite batch migrations rewrite SQL formatting/identifier quotes.
                # Compare columns, constraints and indexes rather than SQL spelling.
                result = {}
                tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
                for (name,) in tables:
                    quoted = '"' + name.replace('"', '""') + '"'
                    indexes = []
                    for row in connection.execute(f"PRAGMA index_list({quoted})"):
                        index = '"' + row[1].replace('"', '""') + '"'
                        columns = connection.execute(f"PRAGMA index_info({index})").fetchall()
                        indexes.append((row[2], row[3], row[4], tuple(columns)))
                    result[name] = {"columns": connection.execute(f"PRAGMA table_info({quoted})").fetchall(),
                                    "foreign_keys": connection.execute(f"PRAGMA foreign_key_list({quoted})").fetchall(),
                                    "indexes": sorted(indexes)}
                return result

        def probe(cwd):
            code = """
import asyncio
import httpx
from app.main import app
async def check():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture/api/v1') as c:
        r=await c.post('/auth/login',json={'email':'rollback@example.invalid','password':'fixture-password-only'})
        assert r.status_code==200,r.text
        h={'Authorization':'Bearer '+r.json()['access_token']}
        r=await c.get('/auth/me',headers=h)
        assert r.status_code==200,r.text
        assert r.json()['user']['email']=='rollback@example.invalid'
    from app.db.session import engine
    await engine.dispose()
asyncio.run(check())
"""
            result = subprocess.run([sys.executable, "-c", code], cwd=cwd, env=env, capture_output=True, text=True, timeout=90)
            if result.returncode:
                raise RuntimeError(result.stderr[-2000:] + "\n" + result.stdout[-1000:])

        run("alembic", "upgrade", "0019")
        initial_schema = schema()
        # This hash is for a public, synthetic local fixture only.
        from app.core.security import hash_password
        with closing(sqlite3.connect(db)) as connection:
            connection.execute("INSERT INTO users(id,email,name,password_hash,is_active,is_superuser,created_at) VALUES(?,?,?,?,?,?,?)",
                               ("release-fixture", "rollback@example.invalid", "Fixture", hash_password("fixture-password-only"), 1, 0,
                                "2026-11-19 00:00:00"))
            connection.commit()
        probe(baseline)
        run("alembic", "upgrade", "head")
        probe(current)
        # Roll back the application first while retaining additive security columns.
        probe(baseline)
        run("alembic", "downgrade", "0019")
        if schema() != initial_schema:
            raise AssertionError("Downgrade did not restore the baseline schema")
        probe(baseline)
        run("alembic", "upgrade", "head")
        probe(current)
        run("alembic", "check")
        print(json.dumps({"status": "passed", "database": "disposable SQLite", "migration": "0019 -> 0021 -> 0019 -> 0021",
                          "app_checks": "old login, new login, old app on expanded schema, old login after downgrade, new login after re-upgrade",
                          "metadata_check": "passed"}))


if __name__ == "__main__":
    main()
