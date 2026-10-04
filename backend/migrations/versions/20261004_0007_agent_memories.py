"""Durable, tenant-scoped simulated agent memories and numeric creator history."""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    vector = Vector(128) if pg else sa.JSON()
    op.create_table("agent_memories",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("population_ref", sa.String(160), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(160), nullable=False), sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("embedding", vector, nullable=False), sa.Column("sentiment", sa.Float(), nullable=False),
        sa.Column("source_simulation_id", sa.String(32), sa.ForeignKey("simulations.id", ondelete="SET NULL")),
        sa.Column("source_post_ids", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_recalled_at", sa.DateTime(timezone=True)), sa.Column("recall_count", sa.Integer(), nullable=False),
        sa.Column("superseded_by", sa.String(32), sa.ForeignKey("agent_memories.id", ondelete="SET NULL")),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="importance_range"),
        sa.CheckConstraint("sentiment >= -1 AND sentiment <= 1", name="sentiment_range"),
        sa.CheckConstraint("kind IN ('episodic','opinion','relationship','reflection')", name="memory_kind"))
    op.create_index("ix_agent_memories_person", "agent_memories", ["org_id", "population_ref"])
    op.create_index("ix_agent_memories_subject", "agent_memories", ["org_id", "subject", "created_at"])
    op.create_index("ix_agent_memories_source_simulation_id", "agent_memories", ["source_simulation_id"])
    if pg:
        op.create_index("ix_agent_memories_cosine", "agent_memories", ["embedding"], postgresql_using="hnsw",
                        postgresql_ops={"embedding": "vector_cosine_ops"})
    op.create_table("agent_creator_affinity",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("population_ref", sa.String(160), nullable=False), sa.Column("subject", sa.String(160), nullable=False),
        sa.Column("familiarity", sa.Float(), nullable=False), sa.Column("affinity", sa.Float(), nullable=False),
        sa.Column("fatigue", sa.Float(), nullable=False), sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decayed_at", sa.DateTime(timezone=True), nullable=False), sa.Column("topic_embedding", vector, nullable=False),
        sa.Column("segment", sa.String(32), nullable=False))
    op.create_index("ix_agent_affinity_person_subject", "agent_creator_affinity", ["org_id", "population_ref", "subject"], unique=True)
    op.create_index("ix_agent_affinity_subject", "agent_creator_affinity", ["org_id", "subject"])


def downgrade():
    op.drop_table("agent_creator_affinity")
    op.drop_table("agent_memories")
