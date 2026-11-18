"""Account recovery, verification, encrypted mail outbox and shared rate counters."""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True)))
    op.add_column("users", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("account_tokens",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True)))
    op.create_index("ix_account_tokens_user_id", "account_tokens", ["user_id"])
    op.create_index("ix_account_tokens_created_at", "account_tokens", ["created_at"])
    op.create_table("mail_outbox",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("encrypted_body", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True)))
    op.create_index("ix_mail_outbox_next_attempt_at", "mail_outbox", ["next_attempt_at"])
    op.create_index("ix_mail_outbox_created_at", "mail_outbox", ["created_at"])
    op.create_table("rate_counters",
        sa.Column("key", sa.String(64), primary_key=True),
        sa.Column("bucket", sa.Integer(), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_rate_counters_expires_at", "rate_counters", ["expires_at"])
    if op.get_context().dialect.name == "postgresql":
        for table in ("account_tokens", "mail_outbox", "rate_counters"):
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")


def downgrade():
    for table in ("rate_counters", "mail_outbox", "account_tokens"):
        op.drop_table(table)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("auth_version")
        batch.drop_column("email_verified_at")
