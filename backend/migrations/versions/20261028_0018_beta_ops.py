"""Beta operations: invite codes for sign-up and an error log for the platform admin."""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("beta_invites",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True), sa.Column("email", sa.String(320)),
        sa.Column("note", sa.String(300), nullable=False), sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.create_index("ix_beta_invites_created_at", "beta_invites", ["created_at"])
    op.create_table("error_events",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.String(10), nullable=False), sa.Column("message", sa.String(500), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False), sa.Column("path", sa.String(300), nullable=False),
        sa.Column("request_id", sa.String(64)), sa.Column("user_id", sa.String(32)), sa.Column("org_id", sa.String(32)))
    op.create_index("ix_error_events_created_at", "error_events", ["created_at"])
    op.create_index("ix_error_events_source_created", "error_events", ["source", "created_at"])


def downgrade():
    op.drop_table("error_events")
    op.drop_table("beta_invites")
