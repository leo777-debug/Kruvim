"""Transactional encrypted outbox and SMTP delivery. Never log bodies or tokens."""
import asyncio
import logging
import smtplib
import ssl
from datetime import timedelta
from email.message import EmailMessage

from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import decrypt, encrypt
from app.db.base import utcnow
from app.db.session import SessionLocal
from app.models import MailOutbox, User

log = logging.getLogger("kruvim.mail")


def enqueue(s, recipient, subject, body, *, expires_at=None):
    row = MailOutbox(recipient=recipient, subject=subject, encrypted_body=encrypt(body),
        next_attempt_at=utcnow(), expires_at=expires_at or utcnow() + timedelta(days=2))
    s.add(row)
    return row


def _send(recipient, subject, body):
    if settings.mail_backend == "console":
        log.info("Development email suppressed; SMTP is not configured")
        return False
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.mail_from, recipient, subject
    message.set_content(body)
    context = ssl.create_default_context()
    connection = (smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15, context=context)
        if settings.smtp_security == "ssl" else smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15))
    with connection as smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=context)
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        if smtp.send_message(message):
            raise RuntimeError("SMTP recipient refused")
    return True


async def dispatch_pending(limit=25):
    if settings.mail_backend != "smtp":
        return
    for _ in range(limit):
        async with SessionLocal() as s:
            now = utcnow()
            row = (await s.execute(select(MailOutbox).where(MailOutbox.delivered_at.is_(None),
                MailOutbox.next_attempt_at <= now, MailOutbox.expires_at > now)
                .order_by(MailOutbox.created_at).limit(1).with_for_update(skip_locked=True))).scalar_one_or_none()
            if row is None:
                return
            row.attempts += 1
            try:
                body = decrypt(row.encrypted_body)
                if not body:
                    raise RuntimeError("Unreadable outbox message")
                if await asyncio.to_thread(_send, row.recipient, row.subject, body):
                    row.delivered_at = utcnow()
                    row.encrypted_body = ""
            except Exception:
                log.warning("Email delivery failed; retry scheduled", extra={"outbox_id": row.id})
            row.next_attempt_at = utcnow() + timedelta(seconds=min(3600, 30 * 2 ** min(row.attempts, 7)))
            await s.commit()


async def notify(user_id, subject, body, *, session=None):
    if session is not None:
        user = await session.get(User, user_id)
        if user and user.is_active:
            enqueue(session, user.email, subject, body)
        return
    async with SessionLocal() as s:
        await notify(user_id, subject, body, session=s)
        await s.commit()
