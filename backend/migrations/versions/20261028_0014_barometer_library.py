"""Barometer library: untouched public country data with provenance, raw text chunks and embeddings."""
import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    vector = Vector(128) if pg else sa.JSON()
    op.create_table("barometer_documents",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("country", sa.String(8), nullable=False),
        sa.Column("publisher", sa.String(240), nullable=False), sa.Column("source_url", sa.String(1000)),
        sa.Column("published_on", sa.Date()), sa.Column("filename", sa.String(300), nullable=False),
        sa.Column("mime", sa.String(120), nullable=False), sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False), sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("encoding", sa.String(40)), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("quarantine_reason", sa.Text()), sa.Column("text_chars", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False), sa.Column("notes", sa.JSON(), nullable=False),
        sa.Column("uploaded_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.CheckConstraint("status IN ('ready','quarantined')", name="barometer_status"))
    op.create_index("ix_barometer_documents_created_at", "barometer_documents", ["created_at"])
    op.create_index("ix_barometer_documents_scope_hash", "barometer_documents", ["org_id", "sha256"])
    op.create_index("ix_barometer_documents_scope_country", "barometer_documents", ["org_id", "country", "status"])
    op.create_table("barometer_chunks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("document_id", sa.String(32), sa.ForeignKey("barometer_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE")),
        sa.Column("country", sa.String(8), nullable=False), sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("location", sa.String(120), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", vector, nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_barometer_chunks_document_id", "barometer_chunks", ["document_id"])
    op.create_index("ix_barometer_chunks_scope_country", "barometer_chunks", ["org_id", "country"])
    if pg:
        op.create_index("ix_barometer_chunks_cosine", "barometer_chunks", ["embedding"], postgresql_using="hnsw",
                        postgresql_ops={"embedding": "vector_cosine_ops"})


def downgrade():
    op.drop_table("barometer_chunks")
    op.drop_table("barometer_documents")
