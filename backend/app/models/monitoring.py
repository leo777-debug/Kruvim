"""Competitor monitoring: watched public feeds that are simulated automatically, and in-app alerts."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class Watch(IdMixin, TimestampMixin, Base):
    """A competitor's public RSS/Atom feed (blog, newsletter, YouTube channel, podcast). New items are tested on
    `audience` and compared with the workspace's own results."""
    __tablename__ = "watches"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    feed_url: Mapped[str] = mapped_column(String(1000))
    format: Mapped[str] = mapped_column(String(40), default="social_post")
    platform: Mapped[str] = mapped_column(String(32), default="x")
    audience: Mapped[dict] = mapped_column(default=dict)
    threshold: Mapped[float] = mapped_column(Float, default=0.5)        # alert when it beats your average by this much
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    seen: Mapped[list] = mapped_column(default=list)                    # item ids already simulated (newest last, capped)
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    last_error: Mapped[str | None] = mapped_column(Text)


class Alert(IdMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"))
    watch_id: Mapped[str | None] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))                       # competitor_outscored | rerun_changed | run_failed
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
