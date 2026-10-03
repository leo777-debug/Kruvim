from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


def record(s: AsyncSession, action: str, *, org_id: str | None = None, user_id: str | None = None,
           target: str | None = None, meta: dict | None = None, ip: str | None = None) -> None:
    s.add(AuditLog(org_id=org_id, user_id=user_id, action=action, target=target, meta=meta or {}, ip=ip))
