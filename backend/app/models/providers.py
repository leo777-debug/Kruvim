"""Model provider configurations. org_id NULL = platform default (managed by superusers)."""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class ProviderConfig(IdMixin, TimestampMixin, Base):
    __tablename__ = "provider_configs"
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120), default="Default")
    preset: Mapped[str] = mapped_column(String(32), default="dryrun")
    provider: Mapped[str] = mapped_column(String(32), default="dryrun")     # dryrun | openai | anthropic
    base_url: Mapped[str] = mapped_column(String(500), default="")
    api_key_enc: Mapped[str | None] = mapped_column(String(2000))
    voice_model: Mapped[str] = mapped_column(String(200), default="")
    report_model: Mapped[str] = mapped_column(String(200), default="")
    vision_model: Mapped[str] = mapped_column(String(200), default="")
    concurrency: Mapped[int] = mapped_column(Integer, default=6)
    temperature: Mapped[float] = mapped_column(Float, default=0.9)
    json_mode: Mapped[bool] = mapped_column(Boolean, default=True)
    price_in: Mapped[float | None] = mapped_column(Float)
    price_cached: Mapped[float | None] = mapped_column(Float)
    price_out: Mapped[float | None] = mapped_column(Float)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True)
