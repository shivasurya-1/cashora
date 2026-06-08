"""convert category enum to string

Revision ID: 7f1d2c3b4a5e
Revises: 31328cd082d0
Create Date: 2026-06-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "7f1d2c3b4a5e"
down_revision: Union[str, Sequence[str], None] = "31328cd082d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    expense_category_enum = postgresql.ENUM(
        "travel",
        "meals",
        "software",
        "office_supplies",
        "others",
        name="expensecategory",
    )

    op.alter_column(
        "expense_requests",
        "category",
        type_=sa.String(length=100),
        existing_type=expense_category_enum,
        postgresql_using="category::text",
        nullable=False,
    )
    op.execute("DROP TYPE IF EXISTS expensecategory")


def downgrade() -> None:
    """Downgrade schema."""
    expense_category_enum = postgresql.ENUM(
        "travel",
        "meals",
        "software",
        "office_supplies",
        "others",
        name="expensecategory",
    )
    expense_category_enum.create(op.get_bind(), checkfirst=True)

    op.alter_column(
        "expense_requests",
        "category",
        type_=expense_category_enum,
        existing_type=sa.String(length=100),
        postgresql_using="category::expensecategory",
        nullable=False,
    )