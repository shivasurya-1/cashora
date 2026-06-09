"""add branches and super admin

Revision ID: 9c8a7b6d5e4f
Revises: 7f1d2c3b4a5e
Create Date: 2026-06-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9c8a7b6d5e4f"
down_revision: Union[str, Sequence[str], None] = "7f1d2c3b4a5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "branches",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("org_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
    )
    op.create_index("ix_branches_org_id", "branches", ["org_id"], unique=False)
    op.create_index("ix_branches_org_id_name", "branches", ["org_id", "name"], unique=True)
    op.create_index("ix_branches_org_id_code", "branches", ["org_id", "code"], unique=True)

    op.add_column("users", sa.Column("branch_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_branch_id", "users", ["branch_id"], unique=False)
    op.create_foreign_key("fk_users_branch_id", "users", "branches", ["branch_id"], ["id"])

    op.execute("ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(20) USING lower(role::text)")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'super_admin'")

    op.drop_constraint("fk_users_branch_id", "users", type_="foreignkey")
    op.drop_index("ix_users_branch_id", table_name="users")
    op.drop_column("users", "branch_id")

    op.drop_index("ix_branches_org_id_code", table_name="branches")
    op.drop_index("ix_branches_org_id_name", table_name="branches")
    op.drop_index("ix_branches_org_id", table_name="branches")
    op.drop_table("branches")
