"""Enable verified CC0 analytics for untouched registry rows; preserve admin decisions."""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    table = sa.Table("data_sources", sa.MetaData(), autoload_with=bind)
    row = bind.execute(sa.select(table).where(table.c.key == "wikipedia")).mappings().first()
    if row and row["status"] == "pending_import" and not row["licence_approved"] and not row["licence_approved_by"]:
        # Freeze the licence evidence at this revision, independently of later catalogue edits.
        entry = dict(status="active", licence_approved=True,
            licence="Wikimedia aggregate analytics/pageview data: CC0 1.0. Article text has separate terms and is not imported.",
            terms_url="https://analytics.wikimedia.org/",
            notes="Publisher analytics portal explicitly dedicates its data to CC0. Verified 2026-10-07. Titles and aggregate counts only; retain safety and geographic checks.")
        # Deliberate admin edits are never overwritten.
        if row["notes"].startswith("Existing connector/public metadata registered"):
            bind.execute(table.update().where(table.c.id == row["id"]).values(**{
                key: entry[key] for key in ("status", "licence_approved", "licence", "terms_url", "notes")}))


def downgrade():
    pass  # Preserve provenance and operator approvals.
