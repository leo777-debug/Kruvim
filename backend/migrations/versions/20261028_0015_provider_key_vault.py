"""Model-provider key vault: one encrypted key per provider per workspace (moved out of provider_configs)."""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

NO_KEY = {"dryrun", "ollama", "lmstudio", "llamacpp", "vllm"}


def upgrade():
    op.create_table("provider_keys",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("org_id", sa.String(32), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("api_key_enc", sa.Text(), nullable=False),
        sa.Column("key_hint", sa.String(40), nullable=False), sa.Column("base_url", sa.String(500)),
        sa.Column("status", sa.String(16), nullable=False), sa.Column("status_message", sa.String(300)),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)), sa.Column("rotated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")))
    op.create_index("ix_provider_keys_created_at", "provider_keys", ["created_at"])
    op.create_index("uq_provider_keys_org_provider", "provider_keys", ["org_id", "provider"], unique=True)

    # Existing workspace keys move into the vault unchanged (same ciphertext); the platform key stays where it is.
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id, org_id, preset, base_url, api_key_enc FROM provider_configs "
                                "WHERE org_id IS NOT NULL AND api_key_enc IS NOT NULL")).fetchall()
    now = datetime.now(UTC)
    seen = set()
    for config_id, org_id, preset, base_url, enc in rows:
        if preset in NO_KEY or (org_id, preset) in seen:
            continue
        seen.add((org_id, preset))
        bind.execute(sa.text("INSERT INTO provider_keys (id, created_at, org_id, provider, api_key_enc, key_hint, base_url, status, "
                             "status_message) VALUES (:id, :now, :org, :provider, :enc, 'saved key', :base, 'unchecked', "
                             "'Moved from an earlier version; check it once.')"),
                     {"id": uuid.uuid4().hex, "now": now, "org": org_id, "provider": preset, "enc": enc,
                      "base": base_url if preset == "custom" else None})
        bind.execute(sa.text("UPDATE provider_configs SET api_key_enc = NULL WHERE id = :id"), {"id": config_id})


def downgrade():
    bind = op.get_bind()
    for org_id, provider, enc in bind.execute(sa.text("SELECT org_id, provider, api_key_enc FROM provider_keys")).fetchall():
        bind.execute(sa.text("UPDATE provider_configs SET api_key_enc = :enc WHERE org_id = :org AND preset = :provider "
                             "AND api_key_enc IS NULL"), {"enc": enc, "org": org_id, "provider": provider})
    op.drop_table("provider_keys")
