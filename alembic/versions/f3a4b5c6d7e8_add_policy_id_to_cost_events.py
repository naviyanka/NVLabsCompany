"""add policy_id to cost_events

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-09-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cost_events") as batch:
        batch.add_column(sa.Column("policy_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_cost_events_policy_id",
            "budget_policies",
            ["policy_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index("ix_cost_events_policy_id", ["policy_id"])


def downgrade() -> None:
    with op.batch_alter_table("cost_events") as batch:
        batch.drop_index("ix_cost_events_policy_id")
        batch.drop_constraint("fk_cost_events_policy_id", type_="foreignkey")
        batch.drop_column("policy_id")
