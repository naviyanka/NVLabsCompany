"""Add database-backed Obsidian vault write grants.

Revision ID: a7c4e9b2d610
Revises: f5b2e9c31a70
Create Date: 2026-09-01
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7c4e9b2d610"
down_revision: Union[str, None] = "f5b2e9c31a70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vault_write_grants",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("tool_id", sa.Uuid(), nullable=False),
        sa.Column("subtree", sa.String(length=1024), nullable=False),
        sa.Column("granted_by", sa.String(length=255), nullable=True),
        sa.Column("granted_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["tool_id"], ["tools.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("company_id", "agent_id", "tool_id", "revoked_at"):
        op.create_index(
            op.f(f"ix_vault_write_grants_{column}"),
            "vault_write_grants",
            [column],
            unique=False,
        )


def downgrade() -> None:
    for column in ("revoked_at", "tool_id", "agent_id", "company_id"):
        op.drop_index(
            op.f(f"ix_vault_write_grants_{column}"),
            table_name="vault_write_grants",
        )
    op.drop_table("vault_write_grants")
