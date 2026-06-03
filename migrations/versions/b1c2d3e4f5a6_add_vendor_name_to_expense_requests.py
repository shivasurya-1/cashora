"""add vendor_name to expense_requests

Revision ID: b1c2d3e4f5a6
Revises: f1c2d3e4a5b6
Create Date: 2026-05-25 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b1c2d3e4f5a6'
down_revision = 'f1c2d3e4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'expense_requests',
        sa.Column('vendor_name', sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('expense_requests', 'vendor_name')
