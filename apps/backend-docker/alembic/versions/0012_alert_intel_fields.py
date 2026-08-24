"""Edge Intelligence fields on candidate_events and alerts.

Persisted enrichment so the channel formatter renders predictive intelligence
(win rate, pool impact, cluster origin) without any post-hoc lookups.

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-24
"""
import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

_INTEL_COLUMNS = [
    sa.Column("win_rate", sa.Float(), nullable=True),
    sa.Column("pool_impact_percentage", sa.Float(), nullable=True),
    sa.Column("cluster_origin", sa.String(255), nullable=True),
    sa.Column("hop_count", sa.Integer(), nullable=True),
    sa.Column("coordinated_flag", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
]


def upgrade():
    for column in _INTEL_COLUMNS:
        op.add_column("candidate_events", column.copy())
        op.add_column("alerts", column.copy())


def downgrade():
    for column in reversed(_INTEL_COLUMNS):
        op.drop_column("alerts", column.name)
        op.drop_column("candidate_events", column.name)
