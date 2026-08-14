"""curated_wallets: Solana-ready + richer metadata.

Revision ID: 0001_curated_wallets_solana
Revises:
Create Date: 2026-01-14
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_curated_wallets_solana"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "curated_wallets", "address",
        existing_type=sa.String(42), type_=sa.String(64), nullable=False,
    )
    op.alter_column(
        "curated_wallets", "chain",
        existing_type=sa.String(20), type_=sa.String(16), nullable=False,
    )
    op.add_column(
        "curated_wallets",
        sa.Column("network_family", sa.String(8), nullable=False, server_default="EVM"),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("category", sa.String(64), nullable=False, server_default="Smart Money"),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.add_column(
        "curated_wallets",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    # The old constraint name came from the prior (removed) migration.
    op.drop_constraint("uq_address_chain", "curated_wallets", type_="unique")
    op.create_unique_constraint("uq_curated_address_chain", "curated_wallets", ["address", "chain"])
    # Drop the backfill server defaults so the application stays authoritative.
    op.execute("ALTER TABLE curated_wallets ALTER COLUMN network_family DROP DEFAULT")
    op.execute("ALTER TABLE curated_wallets ALTER COLUMN category DROP DEFAULT")


def downgrade():
    op.drop_constraint("uq_curated_address_chain", "curated_wallets", type_="unique")
    op.create_unique_constraint("uq_address_chain", "curated_wallets", ["address", "chain"])
    op.drop_column("curated_wallets", "updated_at")
    op.drop_column("curated_wallets", "created_at")
    op.drop_column("curated_wallets", "category")
    op.drop_column("curated_wallets", "network_family")
    op.alter_column(
        "curated_wallets", "chain",
        existing_type=sa.String(16), type_=sa.String(20), nullable=False,
    )
    op.alter_column(
        "curated_wallets", "address",
        existing_type=sa.String(64), type_=sa.String(42), nullable=False,
    )
