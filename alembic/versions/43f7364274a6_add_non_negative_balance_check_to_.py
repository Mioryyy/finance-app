"""add non-negative balance check to accounts

Revision ID: 43f7364274a6
Revises: f20c7cf009f0
Create Date: 2026-10-26 22:38:20.432024

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '43f7364274a6'
down_revision: Union[str, Sequence[str], None] = 'f20c7cf009f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # упадёт, если в базе уже есть наличные или крипта с минусом:
    # такие балансы нужно сначала исправить вручную
    op.create_check_constraint(
        "ck_accounts_balance_non_negative",
        "accounts",
        "type = 'card' OR balance >= 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_accounts_balance_non_negative", "accounts", type_="check")
