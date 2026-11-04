"""Private, project-scoped evidence maintained by workspace members."""
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin


class LibraryFolder(IdMixin, TimestampMixin, Base):
    __tablename__ = "library_folders"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    watch_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_status: Mapped[dict] = mapped_column(default=dict)


class LibraryEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "library_entries"
    __table_args__ = (UniqueConstraint("folder_id", "source_key"),)
    folder_id: Mapped[str] = mapped_column(ForeignKey("library_folders.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(400))
    title: Mapped[str] = mapped_column(String(240))
    data: Mapped[str] = mapped_column(Text)
    region: Mapped[str] = mapped_column(String(16), default="*")
    language: Mapped[str] = mapped_column(String(20), default="")
    tags: Mapped[str] = mapped_column(String(500), default="")
    filename: Mapped[str] = mapped_column(String(240), default="")
    revision: Mapped[int] = mapped_column(Integer, default=1)
