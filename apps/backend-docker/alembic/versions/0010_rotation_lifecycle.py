"""curated_wallets: active-rotation lifecycle fields.

Adds the columns the 300-wallet active-allocation engine needs to track
monitoring state, 30-day transaction velocity, and a decay penalty — plus a
partial index that lets the daily rotation selector scan only active,
high-conviction rows cheaply.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-23
"""
import sqlalchemy as sa
from sqlalchemy import column
from sqlalchemy import text as sa_text

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "curated_wallets",
        sa.Column("is_monitored_active", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("tx_count_30d", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("velocity_penalty", sa.Float(), nullable=False, server_default="1.0"),
    )
    # Partial index: only the active set is scanned by the daily rotation selector.
    op.create_index(
        "idx_curated_active_scoring",
        "curated_wallets",
        [column("is_active"), column("quality_score").desc()],
        postgresql_where=sa_text("is_active = TRUE"),
    )


def downgrade():
    op.drop_index("idx_curated_active_scoring", table_name="curated_wallets")
    op.drop_column("curated_wallets", "velocity_penalty")
    op.drop_column("curated_wallets", "last_activity_at")
    op.drop_column("curated_wallets", "tx_count_30d")
    op.drop_column("curated_wallets", "is_monitored_active")
