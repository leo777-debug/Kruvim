"""Workspace model-provider keys (the key vault). One row per provider per workspace; the key is encrypted at rest."""
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class ProviderKey(IdMixin, TimestampMixin, Base):
    __tablename__ = "provider_keys"
    __table_args__ = (Index("uq_provider_keys_org_provider", "org_id", "provider", unique=True),)
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(40))
    api_key_enc: Mapped[str] = mapped_column(Text)
    key_hint: Mapped[str] = mapped_column(String(40))            # masked form, so listing never decrypts
    base_url: Mapped[str | None] = mapped_column(String(500))     # only for "custom"
    status: Mapped[str] = mapped_column(String(16), default="valid")   # valid | invalid | unchecked
    status_message: Mapped[str | None] = mapped_column(String(300))
    last_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    rotated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
