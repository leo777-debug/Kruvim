"""Revocable, expiring read-only result capabilities."""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("result_shares",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("simulation_id", sa.String(32), sa.ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("view_count", sa.Integer(), nullable=False, server_default="0"))
    for name in ("org_id", "simulation_id", "created_at"):
        op.create_index("ix_result_shares_" + name, "result_shares", [name])


def downgrade():
    op.drop_table("result_shares")
