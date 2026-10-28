"""Barometer library: public country data (statistics, surveys, opinion barometers, reports) kept exactly as published.

The original file is stored untouched and its text is chunked without cleaning, because agents should meet
information the way people do: messy, partial and sometimes contradictory. Every chunk keeps its provenance.
`org_id` NULL means the shared library every signed-in workspace can read (only platform admins add to it)."""
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, TimestampMixin, UTCDateTime


class BarometerDocument(IdMixin, TimestampMixin, Base):
    __tablename__ = "barometer_documents"
    __table_args__ = (
        Index("ix_barometer_documents_scope_hash", "org_id", "sha256"),
        Index("ix_barometer_documents_scope_country", "org_id", "country", "status"),
        CheckConstraint("status IN ('ready','quarantined')", name="barometer_status"),
    )
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(300))
    country: Mapped[str] = mapped_column(String(8))                 # ISO 3166 alpha-2 (or region code like AE-DU), or GLOBAL
    publisher: Mapped[str] = mapped_column(String(240))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    published_on: Mapped[date | None] = mapped_column(Date)
    filename: Mapped[str] = mapped_column(String(300))
    mime: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    storage_key: Mapped[str] = mapped_column(String(500))
    encoding: Mapped[str | None] = mapped_column(String(40))        # how the text was decoded; the bytes are never rewritten
    status: Mapped[str] = mapped_column(String(16))
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[dict] = mapped_column(JSON, default=dict)          # extraction notes, e.g. pages without text
    uploaded_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class BarometerChunk(IdMixin, Base):
    __tablename__ = "barometer_chunks"
    __table_args__ = (Index("ix_barometer_chunks_scope_country", "org_id", "country"),)
    document_id: Mapped[str] = mapped_column(ForeignKey("barometer_documents.id", ondelete="CASCADE"), index=True)
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    country: Mapped[str] = mapped_column(String(8))
    ordinal: Mapped[int] = mapped_column(Integer)
    location: Mapped[str] = mapped_column(String(120))               # "page 4", "sheet Q3 rows 1-40", "lines 120-180"
    text: Mapped[str] = mapped_column(Text)                          # verbatim extracted text
    embedding: Mapped[list] = mapped_column(Vector(128).with_variant(JSON(), "sqlite"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


Index("ix_barometer_chunks_cosine", BarometerChunk.embedding, postgresql_using="hnsw",
      postgresql_ops={"embedding": "vector_cosine_ops"}).ddl_if(dialect="postgresql")
