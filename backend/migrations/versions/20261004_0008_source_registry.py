"""Source registry, native-grain observations and population provenance."""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("data_sources",
        sa.Column("id", sa.String(32), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(80), unique=True, nullable=False), sa.Column("name", sa.String(240), nullable=False),
        sa.Column("publisher", sa.String(240), nullable=False), sa.Column("country", sa.String(8), nullable=False),
        sa.Column("geography_level", sa.String(16), nullable=False), sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("access_method", sa.String(24), nullable=False), sa.Column("licence", sa.Text(), nullable=False),
        sa.Column("attribution", sa.Text(), nullable=False), sa.Column("cadence", sa.String(16), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False), sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False), sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("terms_url", sa.String(2000), nullable=False), sa.Column("licence_approved", sa.Boolean(), nullable=False),
        sa.Column("licence_approved_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("licence_approved_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("reliability >= 0 AND reliability <= 1", name="reliability_range"),
        sa.CheckConstraint("status IN ('active','pending_import','placeholder','deprecated')", name="source_status"),
        sa.CheckConstraint("geography_level IN ('country','emirate','district','point')", name="geography_level"),
        sa.CheckConstraint("access_method IN ('api','file_download','portal_registration','report_pdf','manual')", name="access_method"),
        sa.CheckConstraint("cadence IN ('annual','quarterly','monthly','daily','irregular')", name="source_cadence"))
    op.create_index("ix_data_sources_created_at", "data_sources", ["created_at"])
    op.create_table("source_observations",
        sa.Column("id", sa.String(32), primary_key=True), sa.Column("source_id", sa.String(32), sa.ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("metric", sa.String(120), nullable=False), sa.Column("dimensions", sa.JSON(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False), sa.Column("unit", sa.String(40), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False), sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("geography", sa.String(80), nullable=False), sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_ref", sa.String(2000), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False))
    op.create_index("ix_observations_source_metric_period", "source_observations", ["source_id", "metric", "period_end"])
    op.create_index("ix_observations_geography_metric", "source_observations", ["geography", "metric"])
    op.create_index("ix_observations_fingerprint", "source_observations", ["fingerprint"], unique=True)
    with op.batch_alter_table("signals") as batch:
        batch.add_column(sa.Column("source_id", sa.String(32)))
        batch.create_foreign_key("fk_signals_source_id_data_sources", "data_sources", ["source_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_signals_source_id", ["source_id"])
    with op.batch_alter_table("datasets") as batch:
        batch.add_column(sa.Column("registered_source_id", sa.String(32)))
        batch.create_foreign_key("fk_datasets_registered_source_id_data_sources", "data_sources", ["registered_source_id"], ["id"], ondelete="RESTRICT")
        batch.create_index("ix_datasets_registered_source_id", ["registered_source_id"])
    with op.batch_alter_table("population_versions") as batch:
        for name in ("source_ids", "observation_ids", "attribute_confidence", "conflicts", "coverage_gaps"):
            batch.add_column(sa.Column(name, sa.JSON(), nullable=False, server_default="{}" if name == "attribute_confidence" else "[]"))


def downgrade():
    with op.batch_alter_table("population_versions") as batch:
        for name in ("source_ids", "observation_ids", "attribute_confidence", "conflicts", "coverage_gaps"):
            batch.drop_column(name)
    for table, column in (("datasets", "registered_source_id"), ("signals", "source_id")):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_{column}")
            batch.drop_constraint(f"fk_{table}_{column}_data_sources", type_="foreignkey")
            batch.drop_column(column)
    op.drop_table("source_observations")
    op.drop_table("data_sources")
