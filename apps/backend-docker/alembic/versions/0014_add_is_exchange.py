"""Add is_exchange column to curated_wallets

Revision ID: 0014_add_is_exchange
Revises: 0013_candidate_error_message
Create Date: 2026-09-07
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "curated_wallets",
        sa.Column("is_exchange", sa.Boolean(), nullable=False, server_default=sa.false(), index=True),
    )


def downgrade() -> None:
    op.drop_column("curated_wallets", "is_exchange")