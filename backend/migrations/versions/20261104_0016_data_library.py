"""Private data library folders and evidence rows."""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = depends_on = None


def upgrade():
    op.create_table("library_folders",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.String(32), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("watch_enabled", sa.Boolean(), nullable=False),
        sa.Column("sync_status", sa.JSON(), nullable=False))
    op.create_table("library_entries",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("folder_id", sa.String(32), sa.ForeignKey("library_folders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(400), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("region", sa.String(16), nullable=False),
        sa.Column("language", sa.String(20), nullable=False),
        sa.Column("tags", sa.String(500), nullable=False),
        sa.Column("filename", sa.String(240), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.UniqueConstraint("folder_id", "source_key"))
    for table, columns in (("library_folders", ["created_at", "org_id", "project_id"]),
                           ("library_entries", ["created_at", "folder_id"])):
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade():
    op.drop_table("library_entries")
    op.drop_table("library_folders")
