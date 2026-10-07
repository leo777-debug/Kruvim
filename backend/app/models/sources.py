"""Global public reference sources; original workspace upload files remain tenant-owned."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class DataSource(IdMixin, TimestampMixin, Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        CheckConstraint("reliability >= 0 AND reliability <= 1", name="reliability_range"),
        CheckConstraint("status IN ('active','pending_import','placeholder','deprecated')", name="source_status"),
        CheckConstraint("geography_level IN ('country','emirate','district','point')", name="geography_level"),
        CheckConstraint("access_method IN ('api','file_download','portal_registration','report_pdf','manual')", name="access_method"),
        CheckConstraint("cadence IN ('annual','quarterly','monthly','daily','irregular')", name="source_cadence"),
    )
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(240))
    publisher: Mapped[str] = mapped_column(String(240))
    country: Mapped[str] = mapped_column(String(8))
    geography_level: Mapped[str] = mapped_column(String(16))
    url: Mapped[str] = mapped_column(String(2000))
    access_method: Mapped[str] = mapped_column(String(24))
    licence: Mapped[str] = mapped_column(Text)
    attribution: Mapped[str] = mapped_column(Text)
    cadence: Mapped[str] = mapped_column(String(16))
    reliability: Mapped[float] = mapped_column(Float, default=.5)
    notes: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(24), default="pending_import")
    attributes: Mapped[list] = mapped_column(default=list)
    config: Mapped[dict] = mapped_column(default=dict)
    terms_url: Mapped[str] = mapped_column(String(2000), default="")
    licence_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    licence_approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    licence_approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class SourceObservation(IdMixin, Base):
    __tablename__ = "source_observations"
    __table_args__ = (
        Index("ix_observations_source_metric_period", "source_id", "metric", "period_end"),
        Index("ix_observations_geography_metric", "geography", "metric"),
        Index("ix_observations_fingerprint", "fingerprint", unique=True),
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.id", ondelete="RESTRICT"))
    metric: Mapped[str] = mapped_column(String(120))
    dimensions: Mapped[dict] = mapped_column(default=dict)
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(40))
    period_start: Mapped[datetime] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime] = mapped_column(UTCDateTime)
    geography: Mapped[str] = mapped_column(String(80))
    retrieved_at: Mapped[datetime] = mapped_column(UTCDateTime)
    raw_ref: Mapped[str] = mapped_column(String(2000))
    fingerprint: Mapped[str] = mapped_column(String(64))
