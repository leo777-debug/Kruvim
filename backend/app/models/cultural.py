from datetime import datetime

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, UTCDateTime


class CulturalMoment(IdMixin, Base):
    __tablename__ = "cultural_moments"
    __table_args__ = (Index("uq_cultural_moment_region_day", "region", "day", unique=True),)
    region: Mapped[str] = mapped_column(String(8))
    day: Mapped[datetime] = mapped_column(UTCDateTime)
    note: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(200), default="template")
    usage: Mapped[dict] = mapped_column(default=dict)
