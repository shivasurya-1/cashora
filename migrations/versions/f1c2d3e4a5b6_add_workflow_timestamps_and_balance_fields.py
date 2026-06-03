"""add workflow timestamps and balance fields

Revision ID: f1c2d3e4a5b6
Revises: a9c3e2f1d8b7
Create Date: 2026-05-25
"""
from alembic import op
import sqlalchemy as sa

revision = 'f1c2d3e4a5b6'
down_revision = 'a9c3e2f1d8b7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('expense_requests', sa.Column('approved_at', sa.DateTime(), nullable=True))
    op.add_column('expense_requests', sa.Column('rejected_at', sa.DateTime(), nullable=True))
    op.add_column('expense_requests', sa.Column('paid_at', sa.DateTime(), nullable=True))
    op.add_column('daily_balances', sa.Column('note', sa.Text(), nullable=True))
    op.add_column('daily_balances', sa.Column('amount_in', sa.Float(), nullable=False, server_default='0'))


def downgrade():
    op.drop_column('expense_requests', 'approved_at')
    op.drop_column('expense_requests', 'rejected_at')
    op.drop_column('expense_requests', 'paid_at')
    op.drop_column('daily_balances', 'note')
    op.drop_column('daily_balances', 'amount_in')
