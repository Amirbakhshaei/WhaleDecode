"""Diagnostics column for quarantined (poison-pill) candidate_events.

Rows that fail domain hydration at claim time are marked ``FAILED_HYDRATION``
with the failure reason captured here, so a single corrupt row can be isolated
and inspected without crashing the worker loop.

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-27
"""
import sqlalchemy as sa

from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("candidate_events")]
    if "error_message" not in columns:
        op.add_column(
            "candidate_events",
            sa.Column("error_message", sa.String(512), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [c["name"] for c in inspector.get_columns("candidate_events")]
    if "error_message" in columns:
        op.drop_column("candidate_events", "error_message")
