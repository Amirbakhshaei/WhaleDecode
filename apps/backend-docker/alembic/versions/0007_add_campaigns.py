"""Add campaigns table and candidate_events.campaign_id

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), nullable=False),
        sa.Column("chain", sa.String(length=20), nullable=False),
        sa.Column("token_address", sa.String(length=42), nullable=True),
        sa.Column("total_usd_value", sa.Float(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["wallet_id"], ["curated_wallets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_campaigns_wallet_id", "campaigns", ["wallet_id"])
    op.create_index("ix_campaigns_chain", "campaigns", ["chain"])
    op.create_index("ix_campaigns_status", "campaigns", ["status"])

    op.add_column(
        "candidate_events",
        sa.Column("campaign_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key("fk_candidate_events_campaign_id", "candidate_events", "campaigns", ["campaign_id"], ["id"])
    op.create_index("ix_candidate_events_campaign_id", "candidate_events", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_candidate_events_campaign_id", table_name="candidate_events")
    op.drop_constraint("fk_candidate_events_campaign_id", "candidate_events", type_="foreignkey")
    op.drop_column("candidate_events", "campaign_id")

    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_campaigns_chain", table_name="campaigns")
    op.drop_index("ix_campaigns_wallet_id", table_name="campaigns")
    op.drop_table("campaigns")
