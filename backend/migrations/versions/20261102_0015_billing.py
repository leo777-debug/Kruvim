"""Dodo orders, payment grants and monetary spending reservations."""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = depends_on = None


def org_column(primary=False):
    return sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"),
                     primary_key=primary, nullable=False)


def upgrade():
    op.create_table("billing_accounts", org_column(primary=True),
        sa.Column("customer_id", sa.String(100), unique=True),
        sa.Column("subscription_id", sa.String(100), unique=True),
        sa.Column("status", sa.String(32), nullable=False), sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True)), sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("monthly_remaining", sa.BigInteger(), nullable=False),
        sa.Column("topup_remaining", sa.BigInteger(), nullable=False),
        sa.Column("last_event_at", sa.DateTime(timezone=True)), sa.Column("suspended", sa.Boolean(), nullable=False))
    op.create_table("billing_orders", sa.Column("id", sa.String(32), primary_key=True), org_column(),
        sa.Column("kind", sa.String(24), nullable=False), sa.Column("product_id", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False), sa.Column("session_id", sa.String(100), unique=True),
        sa.Column("checkout_url", sa.String(1000)),
        sa.Column("payment_id", sa.String(100), unique=True), sa.Column("state", sa.String(24), nullable=False),
        sa.Column("budget_micros", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_billing_orders_org_id", "billing_orders", ["org_id"])
    op.create_table("billing_events", sa.Column("id", sa.String(160), primary_key=True),
        sa.Column("kind", sa.String(80), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("billing_grants", sa.Column("id", sa.String(32), primary_key=True), org_column(),
        sa.Column("payment_id", sa.String(100), nullable=False), sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False), sa.Column("reversed", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("payment_id", name="uq_billing_grant_payment"))
    op.create_index("ix_billing_grants_org_id", "billing_grants", ["org_id"])
    op.create_table("spend_reservations", sa.Column("id", sa.String(32), primary_key=True), org_column(),
        sa.Column("period_start", sa.DateTime(timezone=True)), sa.Column("monthly", sa.BigInteger(), nullable=False),
        sa.Column("topup", sa.BigInteger(), nullable=False), sa.Column("actual", sa.BigInteger()),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_spend_reservations_org_id", "spend_reservations", ["org_id"])


def downgrade():
    for table in ("spend_reservations", "billing_grants", "billing_events", "billing_orders", "billing_accounts"):
        op.drop_table(table)
