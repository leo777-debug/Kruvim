"""Beta operations: invite codes for sign-up, and an error log the platform admin can read."""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class BetaInvite(IdMixin, TimestampMixin, Base):
    """A sign-up code for the invite-only beta. Only its hash is stored; the code is shown once when created."""
    __tablename__ = "beta_invites"
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))          # if set, only this address can use it
    note: Mapped[str] = mapped_column(String(300), default="")
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ErrorEvent(IdMixin, TimestampMixin, Base):
    """Unexpected server errors, failed background jobs and browser errors, kept 30 days for the admin view."""
    __tablename__ = "error_events"
    __table_args__ = (Index("ix_error_events_source_created", "source", "created_at"),)
    source: Mapped[str] = mapped_column(String(10))                  # server | job | client
    message: Mapped[str] = mapped_column(String(500))
    detail: Mapped[str] = mapped_column(Text, default="")            # stack or context, never request bodies or keys
    path: Mapped[str] = mapped_column(String(300), default="")
    request_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[str | None] = mapped_column(String(32))
    org_id: Mapped[str | None] = mapped_column(String(32))
