"""Label legacy populations honestly; AE remains the country union without rewriting historical runs."""
import hashlib
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    sources = sa.Table("data_sources", sa.MetaData(), autoload_with=bind)
    identifier = hashlib.sha256(b"placeholder_priors").hexdigest()[:32]
    if not bind.execute(sa.select(sources.c.id).where(sources.c.id == identifier)).first():
        bind.execute(sources.insert().values(id=identifier, created_at=datetime.now(UTC), key="placeholder_priors",
            name="Synthetic placeholder priors", publisher="Kruvim model configuration", country="AE", geography_level="country",
            url="https://github.com/leo777-debug/Kruvim/tree/kruvim/backend/app/services/population", access_method="manual",
            licence="Synthetic model configuration, not measured statistics", attribution="Kruvim synthetic configuration; estimate, source pending",
            cadence="irregular", reliability=0, notes="Unloaded demographic priors are explicit estimates, not official observations.",
            status="placeholder", attributes=["unloaded_population_attributes"], config={}, terms_url="", licence_approved=False))
    versions = sa.Table("population_versions", sa.MetaData(), autoload_with=bind)
    for row in bind.execute(sa.select(versions)).mappings().all():
        if not row["source_ids"]:
            bind.execute(versions.update().where(versions.c.id == row["id"]).values(source_ids=[identifier],
                coverage_gaps=[{"attribute": "legacy_population", "reason": "estimate, source pending; no registered native observations"}]))


def downgrade():
    # Preserve provenance and source records; revision 0008 still supports them.
    pass
