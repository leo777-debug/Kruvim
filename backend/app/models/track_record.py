"""Kruvim's prediction track record.

Forecast: a question answered by a completed simulation, locked (hashed) before its outcome is known, then resolved and
scored against a stated baseline. LedgerEntry: an append-only, hash-chained log of every lock and resolution (launch
forecasts included). Each entry commits to the previous one, so no past prediction can be changed without breaking every
later hash; the ledger holds hashes only, so it can be published without revealing any workspace's content."""
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class Forecast(IdMixin, TimestampMixin, Base):
    __tablename__ = "forecasts"
    __table_args__ = (
        Index("ix_forecasts_org_status", "org_id", "status"),
        CheckConstraint("kind IN ('numeric','binary')", name="forecast_kind"),
        CheckConstraint("status IN ('draft','locked','resolved','void')", name="forecast_status"),
    )
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(String(400))
    domain: Mapped[str] = mapped_column(String(40))                  # launch, statistics, debate, campaign, other
    country: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(10))                    # numeric | binary
    metric: Mapped[str] = mapped_column(String(30))                  # score | positive_share | negative_share
    threshold: Mapped[float | None] = mapped_column(Float)           # binary: "metric >= threshold"
    resolution_criteria: Mapped[str] = mapped_column(Text)
    resolves_on: Mapped[date] = mapped_column(Date)
    baseline_value: Mapped[float] = mapped_column(Float)             # numeric: the value to beat; binary: a probability
    baseline_method: Mapped[str] = mapped_column(String(300))
    model_knowledge_cutoff: Mapped[date | None] = mapped_column(Date)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="SET NULL"), index=True)
    prediction: Mapped[dict] = mapped_column(default=dict)
    prediction_hash: Mapped[str | None] = mapped_column(String(64))
    locked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    outcome: Mapped[dict] = mapped_column(default=dict)              # {"value": ..., "evidence_url": ..., "note": ...}
    outcome_hash: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="draft")
    public: Mapped[bool] = mapped_column(Boolean, default=False)


class LedgerEntry(Base):
    __tablename__ = "forecast_ledger"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    action: Mapped[str] = mapped_column(String(10))                  # lock | resolve | void
    subject_type: Mapped[str] = mapped_column(String(12))            # forecast | launch
    subject_id: Mapped[str] = mapped_column(String(32), index=True)
    org_id: Mapped[str | None] = mapped_column(String(32))           # internal only; never published
    payload_hash: Mapped[str] = mapped_column(String(64))
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64), unique=True)
