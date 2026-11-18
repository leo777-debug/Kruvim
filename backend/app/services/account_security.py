from datetime import timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.errors import AppError
from app.core.security import new_refresh_token, sha256
from app.db.base import utcnow
from app.models import AccountToken, RefreshToken, User
from app.services.mail import enqueue


async def issue(s, user, purpose):
    await s.execute(select(User.id).where(User.id == user.id).with_for_update())
    now = utcnow()
    await s.execute(update(AccountToken).where(AccountToken.user_id == user.id,
        AccountToken.purpose == purpose, AccountToken.used_at.is_(None)).values(used_at=now))
    raw, hashed = new_refresh_token()
    expiry = now + (timedelta(minutes=settings.password_reset_minutes) if purpose == "reset"
        else timedelta(hours=settings.email_verification_hours))
    s.add(AccountToken(user_id=user.id, purpose=purpose, token_hash=hashed, expires_at=expiry))
    route, subject = ("reset-password", "Reset your Kruvim password") if purpose == "reset" else ("verify-email", "Verify your Kruvim email")
    # Fragments keep bearer tokens out of server access logs and referrers.
    link = f"{settings.public_app_url}/{route}#token={raw}"
    enqueue(s, user.email, subject, f"{subject}:\n\n{link}\n\nThis link expires at {expiry.isoformat()} and can be used once. If you did not request it, you can ignore this email.", expires_at=expiry)


async def consume(s, raw, purpose):
    uid = (await s.execute(select(AccountToken.user_id).where(AccountToken.token_hash == sha256(raw),
        AccountToken.purpose == purpose))).scalar_one_or_none()
    if uid is None:
        raise AppError("This link is invalid or has expired.", code="account_token_invalid")
    user = (await s.execute(select(User).where(User.id == uid).with_for_update())).scalar_one()
    now = utcnow()
    claimed = (await s.execute(update(AccountToken).where(AccountToken.token_hash == sha256(raw),
        AccountToken.purpose == purpose, AccountToken.used_at.is_(None), AccountToken.expires_at > now)
        .values(used_at=now).returning(AccountToken.id))).scalar_one_or_none()
    if not claimed or not user.is_active:
        raise AppError("This link is invalid or has expired.", code="account_token_invalid")
    return user


async def revoke_sessions(s, user):
    user.auth_version += 1
    await s.execute(update(RefreshToken).where(RefreshToken.user_id == user.id,
        RefreshToken.revoked_at.is_(None)).values(revoked_at=utcnow()))
    await s.execute(update(AccountToken).where(AccountToken.user_id == user.id,
        AccountToken.purpose == "reset", AccountToken.used_at.is_(None)).values(used_at=utcnow()))
