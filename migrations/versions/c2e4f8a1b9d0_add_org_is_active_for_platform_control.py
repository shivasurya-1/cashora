"""add org is_active for platform control

Revision ID: c2e4f8a1b9d0
Revises: b7f3a1c9d2e4
Create Date: 2026-06-15 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c2e4f8a1b9d0"
down_revision: Union[str, Sequence[str], None] = "b7f3a1c9d2e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("organizations", "is_active")
