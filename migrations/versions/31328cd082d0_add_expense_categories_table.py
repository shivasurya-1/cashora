"""add_expense_categories_table

Revision ID: 31328cd082d0
Revises: b1c2d3e4f5a6
Create Date: 2026-06-05 12:34:29.212292

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '31328cd082d0'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "expense_categories",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    )
    op.create_index("ix_expense_categories_org_id", "expense_categories", ["org_id"], unique=False)
    op.create_index("ix_expense_categories_org_id_slug", "expense_categories", ["org_id", "slug"], unique=True)
    op.create_index("ix_expense_categories_org_id_name", "expense_categories", ["org_id", "name"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_expense_categories_org_id_name", table_name="expense_categories")
    op.drop_index("ix_expense_categories_org_id_slug", table_name="expense_categories")
    op.drop_index("ix_expense_categories_org_id", table_name="expense_categories")
    op.drop_table("expense_categories")
