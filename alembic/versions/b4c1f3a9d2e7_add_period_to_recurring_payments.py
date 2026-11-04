"""add period to recurring payments

Revision ID: b4c1f3a9d2e7
Revises: 16872875d870
Create Date: 2026-11-04 23:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4c1f3a9d2e7'
down_revision: Union[str, Sequence[str], None] = '16872875d870'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # у уже созданных платежей период «month»: раньше других не было
    op.add_column('recurring_payments', sa.Column('period', sa.String(length=8), server_default='month', nullable=False))
    op.add_column('recurring_payments', sa.Column('interval_days', sa.Integer(), nullable=True))
    op.add_column('recurring_payments', sa.Column('anchor_month', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('recurring_payments', 'anchor_month')
    op.drop_column('recurring_payments', 'interval_days')
    op.drop_column('recurring_payments', 'period')
