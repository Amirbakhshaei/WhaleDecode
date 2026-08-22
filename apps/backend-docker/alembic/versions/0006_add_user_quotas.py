"""Add tier and queries_remaining to users

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-05
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tier", sa.String(length=20), server_default="free", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("queries_remaining", sa.Integer(), server_default="5", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "queries_remaining")
    op.drop_column("users", "tier")
