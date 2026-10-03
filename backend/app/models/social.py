"""Private creator analytics credentials and explicit simulation-to-published-post mappings."""
from datetime import datetime

from sqlalchemy import Boolean, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class SocialConnection(IdMixin, TimestampMixin, Base):
    __tablename__ = "social_connections"
    __table_args__ = (Index("uq_social_connections_org_platform", "org_id", "platform", unique=True),)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(24))
    account_id: Mapped[str] = mapped_column(String(200), default="")
    account_name: Mapped[str] = mapped_column(String(200), default="")
    tokens_enc: Mapped[str | None] = mapped_column(Text)
    state_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    state_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    audience: Mapped[dict] = mapped_column(default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_sync_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    sync_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    share_accuracy: Mapped[bool] = mapped_column(Boolean, default=False)


class SocialPost(IdMixin, TimestampMixin, Base):
    __tablename__ = "social_posts"
    __table_args__ = (Index("uq_social_post_variant", "org_id", "simulation_id", "variant", unique=True),
                      Index("uq_social_post_account_post", "connection_id", "post_id", unique=True))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("social_connections.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    variant: Mapped[str] = mapped_column(String(1))
    post_id: Mapped[str] = mapped_column(String(200))
    predicted_score: Mapped[float] = mapped_column(Float)
    prediction: Mapped[dict] = mapped_column(default=dict)
    predicted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    published_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    metrics: Mapped[dict] = mapped_column(default=dict)
    synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
