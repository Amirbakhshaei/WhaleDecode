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
    op.add_column(
        "candidate_events",
        sa.Column("error_message", sa.String(512), nullable=True),
    )


def downgrade():
    op.drop_column("candidate_events", "error_message")
