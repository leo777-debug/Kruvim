"""Data pool: connectors, the signals they collect, hourly regional snapshots (the archive),
barometer datasets and the population versions calibrated from them."""
from __future__ import annotations

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, BigID, IdMixin, TimestampMixin, UTCDateTime, utcnow


class Connector(IdMixin, TimestampMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (Index("ix_connectors_org_key", "org_id", "key", unique=True),)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))  # NULL = platform
    key: Mapped[str] = mapped_column(String(48))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    config: Mapped[dict] = mapped_column(default=dict)
    secrets_enc: Mapped[str | None] = mapped_column(Text)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_status: Mapped[str] = mapped_column(String(16), default="never")   # never | ok | partial | error | skipped
    last_error: Mapped[str | None] = mapped_column(Text)
    last_items: Mapped[int] = mapped_column(Integer, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (Index("ix_signals_region_time", "region", "observed_at"), Index("ix_signals_source_time", "source", "fetched_at"))
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(48))
    kind: Mapped[str] = mapped_column(String(24))            # weather | headline | tone | trend | event | social | economy
    region: Mapped[str] = mapped_column(String(8), default="*")
    title: Mapped[str] = mapped_column(Text, default="")
    value: Mapped[float | None] = mapped_column(Float)
    url: Mapped[str | None] = mapped_column(String(1000))
    lang: Mapped[str | None] = mapped_column(String(8))
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    payload: Mapped[dict] = mapped_column(default=dict)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)


class SignalEmbedding(Base):
    __tablename__ = "signal_embeddings"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(200))
    vector: Mapped[list] = mapped_column(Vector(128).with_variant(JSON(), "sqlite"))


Index("ix_signal_embeddings_cosine", SignalEmbedding.vector, postgresql_using="hnsw",
      postgresql_ops={"vector": "vector_cosine_ops"}).ddl_if(dialect="postgresql")


class RegionSnapshot(Base):
    __tablename__ = "region_snapshots"
    __table_args__ = (Index("ix_region_snapshots_region_hour", "region", "hour", unique=True),)
    id: Mapped[int] = mapped_column(BigID, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(8))
    hour: Mapped[datetime] = mapped_column(UTCDateTime)
    data: Mapped[dict] = mapped_column(default=dict)
    archive_key: Mapped[str | None] = mapped_column(String(500))
    brief: Mapped[str] = mapped_column(Text, default="")
    brief_by: Mapped[str] = mapped_column(String(200), default="template")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Dataset(IdMixin, TimestampMixin, Base):
    __tablename__ = "datasets"
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(40), default="custom")   # arab_barometer | pew | wvs | census | custom
    filename: Mapped[str] = mapped_column(String(300))
    storage_key: Mapped[str] = mapped_column(String(500))
    columns: Mapped[list] = mapped_column(default=list)
    preview: Mapped[list] = mapped_column(default=list)
    rows: Mapped[int] = mapped_column(Integer, default=0)
    mapping: Mapped[dict] = mapped_column(default=dict)
    summary: Mapped[dict] = mapped_column(default=dict)                  # computed marginals per region
    status: Mapped[str] = mapped_column(String(16), default="uploaded")  # uploaded | mapped | applied | error
    error: Mapped[str | None] = mapped_column(Text)


class PopulationVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "population_versions"
    label: Mapped[str] = mapped_column(String(200))
    size: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    priors: Mapped[dict] = mapped_column(default=dict)                   # per-region overrides from datasets
    dataset_ids: Mapped[list] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending | building | ready | error
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    stats: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
