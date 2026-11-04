"""Durable cloud jobs and defaults for direct Supabase Table Editor imports."""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = depends_on = None


def upgrade():
    op.create_table("cloud_jobs", sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("name", sa.String(80), nullable=False), sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("error", sa.Text(), nullable=False))
    op.create_index("ix_cloud_jobs_created_at", "cloud_jobs", ["created_at"])
    op.create_index("ix_cloud_jobs_status", "cloud_jobs", ["status"])
    if op.get_bind().dialect.name == "postgresql":
        for table in ("library_folders", "library_entries"):
            op.alter_column(table, "id", server_default=sa.text("replace(gen_random_uuid()::text, '-', '')"))
            op.alter_column(table, "created_at", server_default=sa.text("now()"))
        for column, value in {"enabled": "true", "watch_enabled": "true", "sync_status": "'{}'::json"}.items():
            op.alter_column("library_folders", column, server_default=sa.text(value))
        for column, value in {"source_key": "'manual:' || gen_random_uuid()::text", "region": "'*'",
                              "language": "''", "tags": "''", "filename": "''", "revision": "1"}.items():
            op.alter_column("library_entries", column, server_default=sa.text(value))


def downgrade():
    op.drop_table("cloud_jobs")
