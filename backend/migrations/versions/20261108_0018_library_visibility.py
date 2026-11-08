"""Private libraries, opt-in public contributions and admin baseline evidence."""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = depends_on = None


def upgrade():
    with op.batch_alter_table("library_folders") as batch:
        batch.add_column(sa.Column("visibility", sa.String(16), nullable=False, server_default="private"))
        batch.create_check_constraint("ck_library_visibility", "visibility in ('private', 'public', 'baseline')")
        batch.create_check_constraint("ck_library_shared_scope", "visibility = 'private' or project_id is null")
        batch.create_index("ix_library_folders_visibility", ["visibility"])


def downgrade():
    with op.batch_alter_table("library_folders") as batch:
        batch.drop_index("ix_library_folders_visibility")
        batch.drop_constraint("ck_library_shared_scope", type_="check")
        batch.drop_constraint("ck_library_visibility", type_="check")
        batch.drop_column("visibility")
