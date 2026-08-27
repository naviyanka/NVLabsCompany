"""add autonomy_policy to agents

Phase 3.4 — per-agent, per-action autonomy policy. JSON so adding an action
bucket needs no migration.

Revision ID: c1d4a8b62f30
Revises: d5b1f7a3c210
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "c1d4a8b62f30"
down_revision: Union[str, None] = "d5b1f7a3c210"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("agents", sa.Column("autonomy_policy", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("agents", "autonomy_policy")
