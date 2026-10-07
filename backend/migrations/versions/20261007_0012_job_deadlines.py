"""Workflow deadlines for orphan recovery."""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("simulations", sa.Column("job_deadline", sa.DateTime(timezone=True), nullable=True))
    op.add_column("simulations", sa.Column("execution_token", sa.String(32), nullable=True))
    op.create_index("ix_simulations_job_deadline", "simulations", ["job_deadline"])


def downgrade():
    op.drop_index("ix_simulations_job_deadline", "simulations")
    op.drop_column("simulations", "execution_token")
    op.drop_column("simulations", "job_deadline")
