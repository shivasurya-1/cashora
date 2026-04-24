"""add_daily_balances_table

Revision ID: d3f99d1c7b2e
Revises: b2d4f1a83e05
Create Date: 2026-04-15 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3f99d1c7b2e"
down_revision: Union[str, Sequence[str], None] = "b2d4f1a83e05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_balances",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("balance_date", sa.Date(), nullable=False),
        sa.Column("opening_balance", sa.Float(), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "balance_date", name="uq_daily_balances_org_date"),
    )
    op.create_index(op.f("ix_daily_balances_org_id"), "daily_balances", ["org_id"], unique=False)
    op.create_index(op.f("ix_daily_balances_balance_date"), "daily_balances", ["balance_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_daily_balances_balance_date"), table_name="daily_balances")
    op.drop_index(op.f("ix_daily_balances_org_id"), table_name="daily_balances")
    op.drop_table("daily_balances")
