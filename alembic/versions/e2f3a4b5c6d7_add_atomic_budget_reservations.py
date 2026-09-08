"""add spent_cents, reserved_cents, and check constraint to budget_policies

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("budget_policies") as batch:
        batch.add_column(sa.Column("spent_cents", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("reserved_cents", sa.Integer(), nullable=False, server_default="0"))

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE budget_policies ADD CONSTRAINT budget_never_overcommitted "
            "CHECK (spent_cents + reserved_cents <= amount);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE budget_policies DROP CONSTRAINT IF EXISTS budget_never_overcommitted;")

    with op.batch_alter_table("budget_policies") as batch:
        batch.drop_column("reserved_cents")
        batch.drop_column("spent_cents")
