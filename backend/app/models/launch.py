"""Launch forecasts: a product announcement tested before release, its prediction locked and hashed, then scored against
the real reaction after release. Locked predictions are immutable; the hash proves they predate the outcome."""
from datetime import date, datetime

from sqlalchemy import Date, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class LaunchForecast(IdMixin, TimestampMixin, Base):
    __tablename__ = 'launch_forecasts'
    __table_args__ = (Index('ix_launch_forecasts_org_company', 'org_id', 'company'),)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'))
    company: Mapped[str] = mapped_column(String(120))
    product: Mapped[str] = mapped_column(String(200))
    announcement_date: Mapped[date] = mapped_column(Date)
    release_date: Mapped[date] = mapped_column(Date)
    # Only data dated before this moment may condition the simulation (defaults to the start of the announcement day, UTC).
    context_cutoff: Mapped[datetime] = mapped_column(UTCDateTime)
    # Launches announced on or before the model's training cutoff are contaminated and never count toward the record.
    model_knowledge_cutoff: Mapped[date | None] = mapped_column(Date)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey('simulations.id', ondelete='SET NULL'), index=True)
    previous_id: Mapped[str | None] = mapped_column(ForeignKey('launch_forecasts.id', ondelete='SET NULL'))
    sources: Mapped[dict] = mapped_column(default=dict)       # youtube_video_ids, reddit_query, window_days
    notes: Mapped[str] = mapped_column(Text, default='')
    background: Mapped[dict] = mapped_column(default=dict)    # pre-cutoff comments collected as simulation seed material
    prediction: Mapped[dict] = mapped_column(default=dict)
    prediction_hash: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome: Mapped[dict] = mapped_column(default=dict)
    scored_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
