"""Private aggregate analytics imports and reusable column mappings."""
import sqlalchemy as sa
from alembic import op

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None


def upgrade():
    def common():
        return [sa.Column('id', sa.String(32), primary_key=True), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.Column('org_id', sa.String(32), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False)]
    op.create_table('analytics_imports', *common(),
        sa.Column('platform', sa.String(24), nullable=False), sa.Column('kind', sa.String(24), nullable=False),
        sa.Column('filename', sa.String(240), nullable=False), sa.Column('storage_key', sa.String(500)),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('mapping', sa.JSON(), nullable=False), sa.Column('summary', sa.JSON(), nullable=False))
    op.create_table('imported_analytics_posts', *common(),
        sa.Column('import_id', sa.String(32), sa.ForeignKey('analytics_imports.id', ondelete='CASCADE'), nullable=False),
        sa.Column('platform', sa.String(24), nullable=False), sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('caption', sa.Text(), nullable=False), sa.Column('format', sa.String(40), nullable=False),
        sa.Column('metadata_fields', sa.JSON(), nullable=False), sa.Column('metrics', sa.JSON(), nullable=False),
        sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('simulation_id', sa.String(32), sa.ForeignKey('simulations.id', ondelete='SET NULL')),
        sa.Column('variant', sa.String(1), nullable=False), sa.Column('prediction', sa.JSON(), nullable=False))
    op.create_table('analytics_mapping_presets', *common(), sa.Column('name', sa.String(120), nullable=False),
        sa.Column('platform', sa.String(24), nullable=False), sa.Column('kind', sa.String(24), nullable=False), sa.Column('mapping', sa.JSON(), nullable=False))
    for table in ('analytics_imports', 'imported_analytics_posts', 'analytics_mapping_presets'):
        op.create_index(f'ix_{table}_org_id', table, ['org_id'])
        op.create_index(f'ix_{table}_created_at', table, ['created_at'])
    op.create_index('ix_analytics_imports_org_status', 'analytics_imports', ['org_id', 'status'])
    op.create_index('ix_imported_analytics_posts_import_id', 'imported_analytics_posts', ['import_id'])
    op.create_index('ix_imported_analytics_posts_simulation_id', 'imported_analytics_posts', ['simulation_id'])
    op.create_index('ix_imported_posts_org_platform_date', 'imported_analytics_posts', ['org_id', 'platform', 'published_at'])
    op.create_index('uq_imported_posts_org_fingerprint', 'imported_analytics_posts', ['org_id', 'fingerprint'], unique=True)
    op.create_index('uq_analytics_preset_org_name', 'analytics_mapping_presets', ['org_id', 'name'], unique=True)
    with op.batch_alter_table('performance_reports') as batch:
        batch.add_column(sa.Column('analytics_post_id', sa.String(32)))
        batch.create_foreign_key('fk_performance_reports_analytics_post_id_imported_analytics_posts', 'imported_analytics_posts', ['analytics_post_id'], ['id'], ondelete='SET NULL')
        batch.create_unique_constraint('uq_performance_reports_analytics_post_id', ['analytics_post_id'])


def downgrade():
    with op.batch_alter_table('performance_reports') as batch:
        batch.drop_constraint('uq_performance_reports_analytics_post_id', type_='unique')
        batch.drop_constraint('fk_performance_reports_analytics_post_id_imported_analytics_posts', type_='foreignkey')
        batch.drop_column('analytics_post_id')
    for table in ('analytics_mapping_presets', 'imported_analytics_posts', 'analytics_imports'):
        op.drop_table(table)
