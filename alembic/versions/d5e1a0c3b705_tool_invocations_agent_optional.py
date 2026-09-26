"""tool_invocations.agent_id nullable (P3.1)

Revision ID: d5e1a0c3b705
Revises: d5e1a0c3b704
Create Date: 2026-09-26

A governed tool call can be made by a principal with no agent: a company API
key on the inbound MCP server, or a user calling the node execute route. Those
calls must be recorded like any other, and with agent_id NOT NULL the insert
failed and took the audit_log entry of the same transaction with it.

Downgrade refuses while agentless rows exist rather than deleting audit
history; remove or reassign them first.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1a0c3b705"
down_revision: str | None = "d5e1a0c3b704"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tool_invocations") as batch:
        batch.alter_column("agent_id", existing_type=sa.Uuid(), nullable=True)


def downgrade() -> None:
    agentless = op.get_bind().execute(
        sa.text("SELECT COUNT(*) FROM tool_invocations WHERE agent_id IS NULL")
    ).scalar()
    if agentless:
        raise RuntimeError(
            f"{agentless} tool_invocations rows have no agent; "
            "remove or reassign them before downgrading"
        )
    with op.batch_alter_table("tool_invocations") as batch:
        batch.alter_column("agent_id", existing_type=sa.Uuid(), nullable=False)
