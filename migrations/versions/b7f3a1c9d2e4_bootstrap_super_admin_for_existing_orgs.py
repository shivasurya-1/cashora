"""bootstrap super admin for existing orgs

Revision ID: b7f3a1c9d2e4
Revises: 9c8a7b6d5e4f
Create Date: 2026-06-09 00:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "b7f3a1c9d2e4"
down_revision: Union[str, Sequence[str], None] = "9c8a7b6d5e4f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Normalize legacy mixed-case roles first (Admin -> admin, etc.).
    op.execute("""
        UPDATE users
        SET role = LOWER(role)
        WHERE role IS NOT NULL
          AND role <> LOWER(role)
    """)

    # One-time bootstrap: for orgs with no super_admin, promote the earliest admin.
    # This resolves the deadlock where no one can assign admin/super_admin in legacy orgs.
    op.execute("""
        WITH promoted_candidates AS (
            SELECT DISTINCT ON (u.org_id) u.id
            FROM users u
            WHERE LOWER(u.role) = 'admin'
              AND NOT EXISTS (
                  SELECT 1
                  FROM users s
                  WHERE s.org_id = u.org_id
                    AND LOWER(s.role) = 'super_admin'
              )
            ORDER BY u.org_id, u.created_at ASC, u.id ASC
        )
        UPDATE users u
        SET role = 'super_admin'
        FROM promoted_candidates p
        WHERE u.id = p.id
    """)


def downgrade() -> None:
    # Best-effort rollback: convert all super_admin back to admin.
    # This mirrors previous migration downgrade behavior.
    op.execute("""
        UPDATE users
        SET role = 'admin'
        WHERE LOWER(role) = 'super_admin'
    """)
