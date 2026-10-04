"""Attach the verified Al Khaleej RSS to untouched, unapproved registry metadata."""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    table = sa.Table("data_sources", sa.MetaData(), autoload_with=bind)
    row = bind.execute(sa.select(table).where(table.c.key == "al_khaleej")).mappings().first()
    if row and not row["licence_approved"] and not row["config"]:
        bind.execute(table.update().where(table.c.id == row["id"]).values(access_method="api",
            config={"adapter": "rss", "feed_url": "https://www.alkhaleej.ae/rssFeed/157", "lang": "ar"},
            notes=row["notes"] + " Publisher-linked UAE RSS returned HTTP 200/XML on 2026-10-04. Commercial permission still pending."))


def downgrade():
    # Keep registered provenance. No observations or publisher approvals are removed.
    pass
