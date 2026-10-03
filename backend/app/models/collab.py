"""Team collaboration (annotations on a simulation's results) and reusable audience templates (the persona library)."""
from __future__ import annotations

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class Annotation(IdMixin, TimestampMixin, Base):
    """A comment pinned to part of a simulation: a heatmap segment, a post, a report section, or the run as a whole."""
    __tablename__ = "annotations"
    simulation_id: Mapped[str] = mapped_column(ForeignKey("simulations.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    anchor: Mapped[str] = mapped_column(String(64), default="general")      # general | segment:<i> | post:<id> | section:<i>
    body: Mapped[str] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class AudienceTemplate(IdMixin, TimestampMixin, Base):
    """A saved audience definition. org_id set = private to that workspace; shared = visible to every workspace
    (the community persona library). Accuracy comes from calibration of the simulations that used it."""
    __tablename__ = "audience_templates"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    filters: Mapped[dict] = mapped_column(default=dict)
    source_citation: Mapped[str] = mapped_column(Text, default="")
    shared: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    accuracy: Mapped[float | None] = mapped_column(Float)
