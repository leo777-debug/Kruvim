"""Private token accounting and durable paused work; plans are public configuration."""
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, UTCDateTime, utcnow


class PlanAllowance(Base):
    __tablename__ = 'plan_allowances'
    plan: Mapped[str] = mapped_column(String(32), primary_key=True)
    daily_credits: Mapped[int] = mapped_column(Integer)


class TokenCall(IdMixin, Base):
    __tablename__ = 'token_calls'
    __table_args__ = (UniqueConstraint('org_id', 'namespace', 'fingerprint', name='uq_token_call_work'),)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    simulation_id: Mapped[str | None] = mapped_column(ForeignKey('simulations.id', ondelete='CASCADE'), index=True)
    namespace: Mapped[str] = mapped_column(String(140))
    fingerprint: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24), default='reserved')
    allocations: Mapped[dict] = mapped_column(default=dict)
    response_enc: Mapped[str | None] = mapped_column(Text)
    usage: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class TokenNotice(IdMixin, Base):
    __tablename__ = 'token_notices'
    __table_args__ = (UniqueConstraint('org_id', 'user_id', 'kind', 'period', name='uq_token_notice_period'),)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id', ondelete='CASCADE'), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    period: Mapped[str] = mapped_column(String(64))
    due_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class ProviderIncident(IdMixin, Base):
    __tablename__ = 'provider_incidents'
    __table_args__ = (UniqueConstraint('provider_key', 'hour', name='uq_provider_incident_hour'),)
    provider_key: Mapped[str] = mapped_column(String(80))
    provider: Mapped[str] = mapped_column(String(32))
    hour: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    raw_error: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProviderHealth(Base):
    __tablename__ = 'provider_health'
    provider_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))
    checked_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
