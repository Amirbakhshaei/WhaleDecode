"""initial migration

Revision ID: 0001
Revises:
Create Date: 2026-07-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("tg_id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("plan", sa.String(20), server_default="free", nullable=False),
        sa.Column("plan_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("daily_chat_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("daily_alert_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tg_id"),
    )
    op.create_table(
        "curated_wallets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("address", sa.String(42), nullable=False),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("label", sa.String(255), server_default="", nullable=False),
        sa.Column("tags", sa.String(500), server_default="", nullable=False),
        sa.Column("quality_score", sa.Float(), server_default="0.5", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_curated_wallets_address", "curated_wallets", ["address"])
    op.create_table(
        "tracked_wallets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("curated_wallets.id"), nullable=False),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("alias", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "wallet_id", name="uq_user_wallet"),
    )
    op.create_table(
        "candidate_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("curated_wallets.id"), nullable=False),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("log_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("block_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("event_type", sa.String(50), server_default="UNKNOWN", nullable=False),
        sa.Column("raw_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), server_default="NEW", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_candidate_dedupe"),
    )
    op.create_table(
        "onchain_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("candidate_id", sa.Integer(), sa.ForeignKey("candidate_events.id"), nullable=False),
        sa.Column("wallet_id", sa.Integer(), sa.ForeignKey("curated_wallets.id"), nullable=False),
        sa.Column("chain", sa.String(20), nullable=False),
        sa.Column("tx_hash", sa.String(66), nullable=False),
        sa.Column("block_number", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("decoded", sa.Text(), server_default="{}", nullable=False),
        sa.Column("enriched_json", sa.Text(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_id", sa.Integer(), sa.ForeignKey("onchain_events.id"), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("priority", sa.String(20), server_default="normal", nullable=False),
        sa.Column("dedupe_key", sa.String(255), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "dedupe_key", name="uq_alert_dedupe"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("trigger_ref_id", sa.Integer(), nullable=True),
        sa.Column("graph_name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("input_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "reasoning_reports",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_run_id", sa.Integer(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("summary", sa.Text(), server_default="", nullable=False),
        sa.Column("risk_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("thesis", sa.Text(), server_default="", nullable=False),
        sa.Column("evidence", sa.Text(), server_default="[]", nullable=False),
        sa.Column("tool_calls", sa.Text(), server_default="[]", nullable=False),
        sa.Column("disclaimer", sa.Text(), server_default="Not financial advice. On-chain data only. DYOR.", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "briefings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("summary_md", sa.Text(), server_default="", nullable=False),
        sa.Column("events_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "tool_call_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_run_id", sa.Integer(), sa.ForeignKey("agent_runs.id"), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("input_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("output_json", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "admin_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True),
        sa.Column("diff_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("admin_audit_logs")
    op.drop_table("tool_call_logs")
    op.drop_table("briefings")
    op.drop_table("reasoning_reports")
    op.drop_table("agent_runs")
    op.drop_table("alerts")
    op.drop_table("onchain_events")
    op.drop_table("candidate_events")
    op.drop_table("tracked_wallets")
    op.drop_table("curated_wallets")
    op.drop_index("ix_curated_wallets_address")
    op.drop_table("users")
