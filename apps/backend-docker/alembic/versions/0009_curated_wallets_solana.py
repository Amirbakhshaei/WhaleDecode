"""curated_wallets: Solana-ready + richer metadata.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-14
"""
import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
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
    # The original curated_wallets table had no (address, chain) uniqueness.
    op.create_unique_constraint("uq_curated_address_chain", "curated_wallets", ["address", "chain"])
    # Drop the backfill server defaults so the application stays authoritative.
    op.execute("ALTER TABLE curated_wallets ALTER COLUMN network_family DROP DEFAULT")
    op.execute("ALTER TABLE curated_wallets ALTER COLUMN category DROP DEFAULT")


def downgrade():
    op.drop_constraint("uq_curated_address_chain", "curated_wallets", type_="unique")
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
