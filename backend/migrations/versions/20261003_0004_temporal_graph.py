"""Preserve closed graph relationships and their validity intervals."""
import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "3491b37de7c7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("graph_edges") as b:
        b.add_column(sa.Column("valid_from_round", sa.Integer(), nullable=False, server_default="-1"))
        b.add_column(sa.Column("valid_until_round", sa.Integer(), nullable=True))
        b.add_column(sa.Column("valid_from_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("valid_until_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE graph_edges SET valid_from_round = round, valid_from_at = created_at")
    with op.batch_alter_table("graph_edges") as b:
        b.alter_column("valid_from_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        b.create_index("ix_graph_edges_current", ["simulation_id", "valid_until_round"])


def downgrade():
    with op.batch_alter_table("graph_edges") as b:
        b.drop_index("ix_graph_edges_current")
        for name in ("valid_from_round", "valid_until_round", "valid_from_at", "valid_until_at"):
            b.drop_column(name)
