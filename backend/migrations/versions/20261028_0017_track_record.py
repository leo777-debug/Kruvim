"""Prediction track record: general forecasts and an append-only hash-chained ledger of locks and resolutions."""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("forecasts",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("question", sa.String(400), nullable=False), sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("country", sa.String(8), nullable=False), sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("metric", sa.String(30), nullable=False), sa.Column("threshold", sa.Float()),
        sa.Column("resolution_criteria", sa.Text(), nullable=False), sa.Column("resolves_on", sa.Date(), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=False), sa.Column("baseline_method", sa.String(300), nullable=False),
        sa.Column("model_knowledge_cutoff", sa.Date()),
        sa.Column("simulation_id", sa.String(32), sa.ForeignKey("simulations.id", ondelete="SET NULL")),
        sa.Column("prediction", sa.JSON(), nullable=False), sa.Column("prediction_hash", sa.String(64)),
        sa.Column("locked_at", sa.DateTime(timezone=True)), sa.Column("outcome", sa.JSON(), nullable=False),
        sa.Column("outcome_hash", sa.String(64)), sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("status", sa.String(10), nullable=False), sa.Column("public", sa.Boolean(), nullable=False),
        sa.CheckConstraint("kind IN ('numeric','binary')", name="forecast_kind"),
        sa.CheckConstraint("status IN ('draft','locked','resolved','void')", name="forecast_status"))
    op.create_index("ix_forecasts_created_at", "forecasts", ["created_at"])
    op.create_index("ix_forecasts_org_status", "forecasts", ["org_id", "status"])
    op.create_index("ix_forecasts_simulation_id", "forecasts", ["simulation_id"])
    op.create_table("forecast_ledger",
        sa.Column("seq", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(10), nullable=False), sa.Column("subject_type", sa.String(12), nullable=False),
        sa.Column("subject_id", sa.String(32), nullable=False), sa.Column("org_id", sa.String(32)),
        sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("entry_hash", sa.String(64), nullable=False, unique=True))
    op.create_index("ix_forecast_ledger_subject_id", "forecast_ledger", ["subject_id"])


def downgrade():
    op.drop_table("forecast_ledger")
    op.drop_table("forecasts")
