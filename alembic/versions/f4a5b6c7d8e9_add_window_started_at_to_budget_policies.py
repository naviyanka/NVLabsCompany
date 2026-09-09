"""add window_started_at to budget_policies

Revision ID: f4a5b6c7d8e9
Revises: f3a4b5c6d7e8
Create Date: 2026-09-09

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4a5b6c7d8e9'
down_revision: str | None = 'f3a4b5c6d7e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("budget_policies") as batch:
        batch.add_column(sa.Column("window_started_at", sa.DateTime(), nullable=True))

    op.execute(
        "UPDATE budget_policies SET window_started_at = created_at WHERE window_started_at IS NULL;"
    )


def downgrade() -> None:
    with op.batch_alter_table("budget_policies") as batch:
        batch.drop_column("window_started_at")
