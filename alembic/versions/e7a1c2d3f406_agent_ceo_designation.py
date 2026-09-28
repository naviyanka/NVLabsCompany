"""agents.is_ceo: one human-appointed CEO per company

Revision ID: e7a1c2d3f406
Revises: e7a1c2d3f405
Create Date: 2026-09-29

The CEO designation is a column, not a role string: only the CEO service
sets it. A partial unique index keeps at most one CEO per company.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f406"
down_revision: str | None = "e7a1c2d3f405"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("agents") as batch:
        batch.add_column(
            sa.Column("is_ceo", sa.Boolean(), nullable=False, server_default=sa.text("false"))
        )
    op.create_index(
        "uq_agents_one_ceo",
        "agents",
        ["company_id"],
        unique=True,
        sqlite_where=sa.text("is_ceo"),
        postgresql_where=sa.text("is_ceo"),
    )


def downgrade() -> None:
    op.drop_index("uq_agents_one_ceo", table_name="agents")
    with op.batch_alter_table("agents") as batch:
        batch.drop_column("is_ceo")
