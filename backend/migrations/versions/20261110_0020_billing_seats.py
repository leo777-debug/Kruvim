"""Give individual seats their own AI allowance and record the paying seat."""
import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "billing_seats",
        sa.Column("org_id", sa.String(32), sa.ForeignKey("billing_accounts.org_id", ondelete="CASCADE"),
                  primary_key=True),
        sa.Column("user_id", sa.String(32), primary_key=True),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("monthly_remaining", sa.BigInteger(), nullable=False),
        sa.Column("topup_remaining", sa.BigInteger(), nullable=False),
    )
    op.create_index("ix_billing_seats_org_period", "billing_seats", ["org_id", "period_start"])
    if op.get_context().dialect.name == "postgresql":
        op.execute("ALTER TABLE billing_seats ENABLE ROW LEVEL SECURITY")
    for table in ("billing_orders", "spend_reservations", "simulations", "surveys"):
        op.add_column(table, sa.Column("seat_user_id", sa.String(32)))
    op.add_column("billing_orders", sa.Column("price_minor", sa.Integer()))


def downgrade():
    op.execute("""
        UPDATE billing_accounts SET
          monthly_remaining = monthly_remaining + COALESCE((
            SELECT SUM(monthly_remaining) FROM billing_seats
            WHERE billing_seats.org_id = billing_accounts.org_id
              AND billing_seats.period_start = billing_accounts.period_start
          ), 0),
          topup_remaining = topup_remaining + COALESCE((
            SELECT SUM(topup_remaining) FROM billing_seats
            WHERE billing_seats.org_id = billing_accounts.org_id
          ), 0)
    """)
    with op.batch_alter_table("billing_orders") as batch:
        batch.drop_column("price_minor")
    for table in ("billing_orders", "spend_reservations", "simulations", "surveys"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("seat_user_id")
    op.drop_table("billing_seats")
