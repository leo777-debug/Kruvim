"""Beta operations: who may sign up, and a durable error log for the platform admin view."""
from __future__ import annotations

import logging
import re
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import Forbidden
from app.core.security import sha256
from app.db.base import utcnow
from app.db.session import session_scope
from app.models import BetaInvite, ErrorEvent

log = logging.getLogger("kruvim.ops")
RETENTION = timedelta(days=30)
_SECRETS = re.compile(r"(sk-[A-Za-z0-9_-]{8,}|krv_[A-Za-z0-9_-]{8,}|AIza[0-9A-Za-z_-]{20,}|Bearer\s+\S+|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_.-]+)")


def scrub(text: str) -> str:
    """Error text can quote headers or provider messages: never keep anything that looks like a key or token."""
    return _SECRETS.sub("[redacted]", text or "")


async def record_error(source: str, message: str, *, detail: str = "", path: str = "", request_id: str | None = None,
                       user_id: str | None = None, org_id: str | None = None) -> None:
    """Best effort: recording an error must never cause another one."""
    try:
        async with session_scope() as s:
            s.add(ErrorEvent(source=source, message=scrub(message)[:500], detail=scrub(detail)[-4000:], path=(path or "")[:300],
                             request_id=request_id, user_id=user_id, org_id=org_id))
            await s.execute(delete(ErrorEvent).where(ErrorEvent.created_at < utcnow() - RETENTION))
    except Exception:
        log.warning("could not record an error event", exc_info=True)


# ---- invite-only sign-up -----------------------------------------------------------------------------------------------
def allowlisted(email: str) -> bool:
    email = email.lower()
    for entry in settings.signup_allowlist:
        entry = entry.strip().lower()
        if entry and (email == entry or (entry.startswith("@") and email.endswith(entry))):
            return True
    return False


async def admit(s: AsyncSession, email: str, code: str | None) -> BetaInvite | None:
    """Raise unless this sign-up is allowed; returns the invite that was used (its use is counted atomically)."""
    if settings.registration_open or allowlisted(email):
        return None
    if not code:
        raise Forbidden("Kruvim is invite-only right now. Enter your invite code, or ask us for one.", code="registration_closed")
    inv = (await s.execute(select(BetaInvite).where(BetaInvite.code_hash == sha256(code.strip())))).scalar_one_or_none()
    now = utcnow()
    if (not inv or inv.revoked_at or inv.expires_at.replace(tzinfo=now.tzinfo) < now
            or (inv.email and inv.email.lower() != email.lower())):
        raise Forbidden("This invite code isn't valid for this email address, or it has expired.", code="invite_invalid")
    used = await s.execute(update(BetaInvite).where(BetaInvite.id == inv.id, BetaInvite.uses < BetaInvite.max_uses)
                           .values(uses=BetaInvite.uses + 1))
    if not used.rowcount:
        raise Forbidden("This invite code has already been used.", code="invite_used")
    return inv
