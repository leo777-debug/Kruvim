"""Launch forecasts: locked, hashed predictions scored against real post-release reaction."""
import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('launch_forecasts',
        sa.Column('id', sa.String(32), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('org_id', sa.String(32), sa.ForeignKey('organizations.id', ondelete='CASCADE', name='fk_launch_forecasts_org_id_organizations'), nullable=False),
        sa.Column('created_by', sa.String(32), sa.ForeignKey('users.id', ondelete='SET NULL', name='fk_launch_forecasts_created_by_users')),
        sa.Column('company', sa.String(120), nullable=False), sa.Column('product', sa.String(200), nullable=False),
        sa.Column('announcement_date', sa.Date(), nullable=False), sa.Column('release_date', sa.Date(), nullable=False),
        sa.Column('context_cutoff', sa.DateTime(timezone=True), nullable=False), sa.Column('model_knowledge_cutoff', sa.Date()),
        sa.Column('simulation_id', sa.String(32), sa.ForeignKey('simulations.id', ondelete='SET NULL', name='fk_launch_forecasts_simulation_id_simulations')),
        sa.Column('previous_id', sa.String(32), sa.ForeignKey('launch_forecasts.id', ondelete='SET NULL', name='fk_launch_forecasts_previous_id_launch_forecasts')),
        sa.Column('sources', sa.JSON(), nullable=False), sa.Column('notes', sa.Text(), nullable=False),
        sa.Column('background', sa.JSON(), nullable=False), sa.Column('prediction', sa.JSON(), nullable=False),
        sa.Column('prediction_hash', sa.String(64)), sa.Column('locked_at', sa.DateTime(timezone=True)),
        sa.Column('outcome', sa.JSON(), nullable=False), sa.Column('scored_at', sa.DateTime(timezone=True)))
    op.create_index('ix_launch_forecasts_org_id', 'launch_forecasts', ['org_id'])
    op.create_index('ix_launch_forecasts_created_at', 'launch_forecasts', ['created_at'])
    op.create_index('ix_launch_forecasts_simulation_id', 'launch_forecasts', ['simulation_id'])
    op.create_index('ix_launch_forecasts_org_company', 'launch_forecasts', ['org_id', 'company'])


def downgrade():
    op.drop_table('launch_forecasts')
