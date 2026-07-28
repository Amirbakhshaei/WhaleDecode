"""fix tg_id to BigInteger

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "tg_id", type_=sa.BigInteger(), existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    op.alter_column("users", "tg_id", type_=sa.Integer(), existing_type=sa.BigInteger(), nullable=False)
