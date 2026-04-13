"""convert_payment_method_enum_to_varchar

Revision ID: b2d4f1a83e05
Revises: a1f3e9c72d04
Create Date: 2026-03-03 16:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d4f1a83e05'
down_revision: Union[str, Sequence[str], None] = 'a1f3e9c72d04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Convert payment_method column from native PostgreSQL enum to varchar.
    
    This avoids SQLAlchemy's enum name vs value mismatch (BANK_TRANSFER vs bank_transfer).
    Pydantic handles input validation at the API layer, so native PG enums are unnecessary.
    """
    # Use USING clause to cast the existing paymentmethod enum values to text
    op.execute(
        "ALTER TABLE expense_requests "
        "ALTER COLUMN payment_method TYPE VARCHAR(50) "
        "USING payment_method::text"
    )

    # Drop the now-unused paymentmethod enum type from PostgreSQL
    op.execute("DROP TYPE IF EXISTS paymentmethod")


def downgrade() -> None:
    """Revert varchar back to native PostgreSQL enum."""
    # Recreate the enum type
    op.execute(
        "CREATE TYPE paymentmethod AS ENUM "
        "('upi', 'bank_transfer', 'cash', 'cheque', 'neft', 'rtgs', 'imps', 'other')"
    )
    # Cast the varchar column back to the enum type
    op.execute(
        "ALTER TABLE expense_requests "
        "ALTER COLUMN payment_method TYPE paymentmethod "
        "USING payment_method::paymentmethod"
    )
