"""add reservation state to cost_events

Two-phase budget reservation. A cost_events row written before a provider call
holds the estimated spend (status='reserved', expires_at set) so concurrent
workers see the hold in the same window sum that committed spend lands in.
After the call the row is reconciled to the exact cost (status='committed') or
released (status='released').

Existing rows are settled spend, so they backfill to 'committed'.

Revision ID: a4e2c8b91f50
Revises: c1d4a8b62f30
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "a4e2c8b91f50"
down_revision: Union[str, None] = "c1d4a8b62f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cost_events",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="committed",
        ),
    )
    op.add_column(
        "cost_events", sa.Column("expires_at", sa.DateTime(), nullable=True)
    )
    # The window sum filters on status, and on (scope, occurred_at) already.
    op.create_index("ix_cost_events_status", "cost_events", ["status"])


def downgrade() -> None:
    op.drop_index("ix_cost_events_status", table_name="cost_events")
    op.drop_column("cost_events", "expires_at")
    op.drop_column("cost_events", "status")
