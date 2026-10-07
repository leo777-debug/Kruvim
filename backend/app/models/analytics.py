"""Workspace-owned aggregate analytics; never individual follower records."""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class AnalyticsImport(IdMixin, TimestampMixin, Base):
    __tablename__ = 'analytics_imports'
    __table_args__ = (Index('ix_analytics_imports_org_status', 'org_id', 'status'),)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    platform: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(24))
    filename: Mapped[str] = mapped_column(String(240))
    storage_key: Mapped[str | None] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(24), default='preview')
    mapping: Mapped[dict] = mapped_column(default=dict)
    summary: Mapped[dict] = mapped_column(default=dict)


class ImportedAnalyticsPost(IdMixin, TimestampMixin, Base):
    __tablename__ = 'imported_analytics_posts'
    __table_args__ = (Index('ix_imported_posts_org_platform_date', 'org_id', 'platform', 'published_at'),
        Index('uq_imported_posts_org_fingerprint', 'org_id', 'fingerprint', unique=True))
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    import_id: Mapped[str] = mapped_column(ForeignKey('analytics_imports.id', ondelete='CASCADE'), index=True)
    platform: Mapped[str] = mapped_column(String(24))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    caption: Mapped[str] = mapped_column(Text, default='')
    format: Mapped[str] = mapped_column(String(40), default='unknown')
    metadata_fields: Mapped[dict] = mapped_column(default=dict)
    metrics: Mapped[dict] = mapped_column(default=dict)
    fingerprint: Mapped[str] = mapped_column(String(64))
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey('simulations.id', ondelete='SET NULL'), index=True)
    variant: Mapped[str] = mapped_column(String(1), default='A')
    prediction: Mapped[dict] = mapped_column(default=dict)


class AnalyticsMappingPreset(IdMixin, TimestampMixin, Base):
    __tablename__ = 'analytics_mapping_presets'
    __table_args__ = (Index('uq_analytics_preset_org_name', 'org_id', 'name', unique=True),)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(120))
    platform: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(24))
    mapping: Mapped[dict] = mapped_column(default=dict)
