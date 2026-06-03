"""add_opening_balance_to_org_and_payments_table

Revision ID: a9c3e2f1d8b7
Revises: 175a58ef6150
Create Date: 2026-05-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9c3e2f1d8b7"
down_revision: Union[str, Sequence[str], None] = "175a58ef6150"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add opening_balance column to organizations
    op.add_column(
        "organizations",
        sa.Column("opening_balance", sa.Float(), nullable=False, server_default="0.0"),
    )

    # Create payments table
    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("payment_id", sa.String(length=50), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("payment_method", sa.String(length=20), nullable=False),
        sa.Column("transaction_id", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="completed"),
        sa.Column("payee_vpa", sa.String(length=255), nullable=True),
        sa.Column("payee_name", sa.String(length=255), nullable=True),
        sa.Column("transaction_note", sa.String(length=500), nullable=True),
        sa.Column("upi_txn_id", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("recorded_by_user_id", sa.Integer(), nullable=True),
        sa.Column(
            "payment_timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["expense_id"], ["expense_requests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["recorded_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("payment_id"),
    )
    op.create_index(op.f("ix_payments_org_id"), "payments", ["org_id"], unique=False)
    op.create_index(op.f("ix_payments_expense_id"), "payments", ["expense_id"], unique=False)
    op.create_index(op.f("ix_payments_payment_id"), "payments", ["payment_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_payment_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_expense_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_org_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_column("organizations", "opening_balance")
