"""Edge Intelligence schema: wallet_profiles + funding_edges (Modules 1 & 2).

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-24
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "wallet_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("address", sa.String(80), nullable=False, index=True),
        sa.Column("historical_win_rate_30d", sa.Float(), nullable=False, server_default="0"),
        sa.Column("avg_holding_period_days", sa.Float(), nullable=False, server_default="0"),
        sa.Column("primary_strategy", sa.String(50), nullable=False, server_default="Unknown"),
        sa.Column("total_pnl_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recent_actions_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("sample_size_30d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="self_observed"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("chain", "address", name="uq_wallet_profile_chain_addr"),
    )
    op.create_table(
        "funding_edges",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("child_address", sa.String(80), nullable=False, index=True),
        sa.Column("parent_address", sa.String(80), nullable=False, index=True),
        sa.Column("tx_hash", sa.String(80), nullable=False),
        sa.Column("block_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hops_from_root", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("root_address", sa.String(80), nullable=False, server_default="", index=True),
        sa.Column("root_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("child_address", "tx_hash", name="uq_funding_edge_child_tx"),
    )


def downgrade():
    op.drop_table("funding_edges")
    op.drop_table("wallet_profiles")
