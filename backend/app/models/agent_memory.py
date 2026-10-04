"""Workspace-owned simulated experiences, never part of shared audience templates."""
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, UTCDateTime, utcnow


class AgentMemory(IdMixin, Base):
    __tablename__ = "agent_memories"
    __table_args__ = (
        Index("ix_agent_memories_person", "org_id", "population_ref"),
        Index("ix_agent_memories_subject", "org_id", "subject", "created_at"),
        CheckConstraint("importance >= 0 AND importance <= 1", name="importance_range"),
        CheckConstraint("sentiment >= -1 AND sentiment <= 1", name="sentiment_range"),
        CheckConstraint("kind IN ('episodic','opinion','relationship','reflection')", name="memory_kind"),
    )
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    population_ref: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(20))
    text: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(160))
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    embedding: Mapped[list] = mapped_column(Vector(128).with_variant(JSON(), "sqlite"))
    sentiment: Mapped[float] = mapped_column(Float, default=0)
    source_simulation_id: Mapped[str | None] = mapped_column(ForeignKey("simulations.id", ondelete="SET NULL"), index=True)
    source_post_ids: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_recalled_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    recall_count: Mapped[int] = mapped_column(Integer, default=0)
    superseded_by: Mapped[str | None] = mapped_column(ForeignKey("agent_memories.id", ondelete="SET NULL"))


Index("ix_agent_memories_cosine", AgentMemory.embedding, postgresql_using="hnsw",
      postgresql_ops={"embedding": "vector_cosine_ops"}).ddl_if(dialect="postgresql")


class AgentCreatorAffinity(IdMixin, Base):
    __tablename__ = "agent_creator_affinity"
    __table_args__ = (Index("ix_agent_affinity_person_subject", "org_id", "population_ref", "subject", unique=True),
                      Index("ix_agent_affinity_subject", "org_id", "subject"))
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))
    population_ref: Mapped[str] = mapped_column(String(160))
    subject: Mapped[str] = mapped_column(String(160))
    familiarity: Mapped[float] = mapped_column(Float, default=0)
    affinity: Mapped[float] = mapped_column(Float, default=0)
    fatigue: Mapped[float] = mapped_column(Float, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # Decay must not alter the exposure date or be applied twice by recall + cron.
    decayed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    topic_embedding: Mapped[list] = mapped_column(Vector(128).with_variant(JSON(), "sqlite"))
    segment: Mapped[str] = mapped_column(String(32), default="stakeholder")
