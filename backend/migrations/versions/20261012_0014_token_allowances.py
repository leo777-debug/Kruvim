"""Daily allowances, encrypted call receipts and resumable token pauses."""
import sqlalchemy as sa
from alembic import op

revision = '0014'
down_revision = '0013'
branch_labels = depends_on = None


def upgrade():
    for name, typ, default in [('topup_balance', sa.Integer(), '0'), ('daily_credits_used', sa.Integer(), '0'),
                               ('daily_credit_day', sa.String(10), '')]:
        op.add_column('organizations', sa.Column(name, typ, nullable=False, server_default=default))
    for name, typ, default in [('last_status', sa.String(32), 'unknown'), ('last_status_at', sa.DateTime(timezone=True), None),
                               ('last_error', sa.Text(), None)]:
        op.add_column('provider_configs', sa.Column(name, typ, nullable=default is None, server_default=default))
    op.add_column('simulations', sa.Column('billing_epoch', sa.String(32), nullable=False, server_default=''))
    op.execute('UPDATE simulations SET billing_epoch = id')
    for table, name in [('simulations', 'pause_state'), ('simulations', 'checkpoint'), ('surveys', 'pause_state')]:
        op.add_column(table, sa.Column(name, sa.JSON(), nullable=False, server_default='{}'))
    op.create_table('plan_allowances', sa.Column('plan', sa.String(32), primary_key=True),
                    sa.Column('daily_credits', sa.Integer(), nullable=False))
    op.create_table('token_calls', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('org_id', sa.String(32), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('simulation_id', sa.String(32), sa.ForeignKey('simulations.id', ondelete='CASCADE')),
        sa.Column('namespace', sa.String(140), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('allocations', sa.JSON(), nullable=False),
        sa.Column('response_enc', sa.Text()), sa.Column('usage', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('org_id', 'namespace', 'fingerprint', name='uq_token_call_work'))
    op.create_index('ix_token_calls_org_id', 'token_calls', ['org_id'])
    op.create_index('ix_token_calls_simulation_id', 'token_calls', ['simulation_id'])
    op.create_table('token_notices', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('org_id', sa.String(32), sa.ForeignKey('organizations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.String(32), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False), sa.Column('period', sa.String(64), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True)), sa.Column('delivered_at', sa.DateTime(timezone=True)),
        sa.UniqueConstraint('org_id', 'user_id', 'kind', 'period', name='uq_token_notice_period'))
    for name in ['org_id', 'user_id', 'due_at']:
        op.create_index('ix_token_notices_' + name, 'token_notices', [name])
    op.create_table('provider_incidents', sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('provider_key', sa.String(80), nullable=False), sa.Column('provider', sa.String(32), nullable=False),
        sa.Column('hour', sa.String(16), nullable=False), sa.Column('category', sa.String(32), nullable=False),
        sa.Column('raw_error', sa.Text(), nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('provider_key', 'hour', name='uq_provider_incident_hour'))
    op.create_table('provider_health', sa.Column('provider_key', sa.String(80), primary_key=True),
        sa.Column('provider', sa.String(32), nullable=False), sa.Column('status', sa.String(32), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), nullable=False), sa.Column('last_error', sa.Text()))
    # Preserve purchased/admin-added credit in its own non-expiring bucket.
    connection = op.get_bind()
    rows = connection.execute(sa.text('SELECT id, credits_balance FROM organizations')).all()
    for org_id, balance in rows:
        monthly = topup = 0
        for delta, reason in connection.execute(sa.text(
                'SELECT delta, reason FROM credit_ledger WHERE org_id=:id ORDER BY created_at, id'), {'id': org_id}):
            if delta > 0 and reason in ('purchase', 'admin_adjust'):
                topup += delta
            elif delta > 0:
                monthly += delta
            else:
                from_month = min(monthly, -delta)
                monthly -= from_month
                topup = max(0, topup + delta + from_month)
        connection.execute(sa.text('UPDATE organizations SET topup_balance=:v WHERE id=:id'),
                           {'v': min(max(0, balance), topup), 'id': org_id})


def downgrade():
    for table in ('provider_health', 'provider_incidents', 'token_notices', 'token_calls', 'plan_allowances'):
        op.drop_table(table)
    for table, columns in [('surveys', ['pause_state']), ('simulations', ['checkpoint', 'pause_state', 'billing_epoch']),
                           ('provider_configs', ['last_error', 'last_status_at', 'last_status']),
                           ('organizations', ['daily_credit_day', 'daily_credits_used', 'topup_balance'])]:
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_column(column)
