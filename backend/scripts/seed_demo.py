"""Create a local demo account + project for development (never run against production).

    python -m scripts.seed_demo            # uses the defaults below
    KRUVIM_DEMO_EMAIL=... KRUVIM_DEMO_PASSWORD=... python -m scripts.seed_demo
"""
from __future__ import annotations

import asyncio
import os

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import engine, session_scope
from app.models import Base, Membership, Organization, Project, User
from app.services.quotas import ensure_monthly_grant

DEMO_EMAIL = os.environ.get("KRUVIM_DEMO_EMAIL", "demo@kruvim.local")
DEMO_PASSWORD = os.environ.get("KRUVIM_DEMO_PASSWORD", "kruvim-demo-2026")


async def main():
    if settings.is_prod:
        raise SystemExit("Refusing to seed demo data in production.")
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with session_scope() as s:
        u = (await s.execute(select(User).where(User.email == DEMO_EMAIL))).scalar_one_or_none()
        if u:
            print(f"Demo user exists: {DEMO_EMAIL}")
            return
        first = (await s.execute(select(User).limit(1))).scalar_one_or_none() is None
        u = User(email=DEMO_EMAIL, name="Demo Creator", password_hash=hash_password(DEMO_PASSWORD), is_superuser=first)
        org = Organization(name="Demo Studio", slug="demo-studio", plan="pro", max_concurrent=3)
        s.add_all([u, org])
        await s.flush()
        s.add(Membership(org_id=org.id, user_id=u.id, role="owner"))
        s.add(Project(org_id=org.id, name="Ramadan fitness campaign", description="Short-form launch for a Gulf gym brand", created_by=u.id))
        await ensure_monthly_grant(s, org)
    print(f"Created {DEMO_EMAIL} (superuser={first}) with workspace 'Demo Studio'")


if __name__ == "__main__":
    asyncio.run(main())
