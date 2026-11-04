"""Durable payment fulfilment and integer-microdirham spending reservations."""
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, UTCDateTime, utcnow


class BillingAccount(Base):
    __tablename__ = "billing_accounts"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    subscription_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="inactive")
    seats: Mapped[int] = mapped_column(Integer, default=1)
    period_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    period_end: Mapped[datetime | None] = mapped_column(UTCDateTime)
    monthly_remaining: Mapped[int] = mapped_column(BigInteger, default=0)
    topup_remaining: Mapped[int] = mapped_column(BigInteger, default=0)
    last_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    suspended: Mapped[bool] = mapped_column(default=False)


class BillingOrder(IdMixin, Base):
    __tablename__ = "billing_orders"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(24))
    product_id: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    session_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    checkout_url: Mapped[str | None] = mapped_column(String(1000))
    payment_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    state: Mapped[str] = mapped_column(String(24), default="pending")
    budget_micros: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BillingEvent(Base):
    __tablename__ = "billing_events"
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    kind: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BillingGrant(IdMixin, Base):
    __tablename__ = "billing_grants"
    __table_args__ = (UniqueConstraint("payment_id", name="uq_billing_grant_payment"),)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    payment_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(24))
    amount: Mapped[int] = mapped_column(BigInteger)
    reversed: Mapped[bool] = mapped_column(default=False)


class SpendReservation(IdMixin, Base):
    __tablename__ = "spend_reservations"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    period_start: Mapped[datetime | None] = mapped_column(UTCDateTime)
    monthly: Mapped[int] = mapped_column(BigInteger)
    topup: Mapped[int] = mapped_column(BigInteger)
    actual: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(24), default="reserved")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
