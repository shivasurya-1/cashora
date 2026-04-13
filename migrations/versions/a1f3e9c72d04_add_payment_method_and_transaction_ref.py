"""add_payment_method_and_transaction_reference

Revision ID: a1f3e9c72d04
Revises: 41c2e4b7a899
Create Date: 2026-03-03 15:17:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1f3e9c72d04'
down_revision: Union[str, Sequence[str], None] = '41c2e4b7a899'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create the PaymentMethod enum type in PostgreSQL
    payment_method_enum = sa.Enum(
        'upi', 'bank_transfer', 'cash', 'cheque', 'neft', 'rtgs', 'imps', 'other',
        name='paymentmethod'
    )
    payment_method_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        'expense_requests',
        sa.Column('payment_method', sa.Enum(
            'upi', 'bank_transfer', 'cash', 'cheque', 'neft', 'rtgs', 'imps', 'other',
            name='paymentmethod'
        ), nullable=True)
    )
    op.add_column(
        'expense_requests',
        sa.Column('transaction_reference', sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('expense_requests', 'transaction_reference')
    op.drop_column('expense_requests', 'payment_method')

    # Drop the enum type from PostgreSQL
    payment_method_enum = sa.Enum(name='paymentmethod')
    payment_method_enum.drop(op.get_bind(), checkfirst=True)
