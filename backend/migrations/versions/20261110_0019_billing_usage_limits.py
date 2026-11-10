"""Shared AI request and spending limits."""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_usage_windows",
        sa.Column("scope", sa.String(48), primary_key=True),
        sa.Column("bucket", sa.Integer(), nullable=False),
        sa.Column("used", sa.BigInteger(), nullable=False),
    )
    if op.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE billing_usage_windows ENABLE ROW LEVEL SECURITY")
    op.add_column("spend_reservations", sa.Column("platform_bucket", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("spend_reservations") as batch:
        batch.drop_column("platform_bucket")
    op.drop_table("billing_usage_windows")
