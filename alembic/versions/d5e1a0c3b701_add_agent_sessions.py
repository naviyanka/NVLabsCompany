"""add agent_sessions table (ws01)

Revision ID: d5e1a0c3b701
Revises: b8d9e0f1a2c3
Create Date: 2026-09-26

AgentSessionRecord is the canonical session for an agent conversation or
run. Transcript, tool calls, spend, checkpoints and heartbeat runs link to it
through nullable session_id columns added in ws02 (d5e1a0c3b702).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1a0c3b701"
down_revision: str | None = "b8d9e0f1a2c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "agent_sessions",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "agent_id", uuid_type, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id",
            uuid_type,
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("adapter_type", sa.String(length=100), nullable=False, server_default="unknown"),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column(
            "llm_connection_id",
            uuid_type,
            sa.ForeignKey("llm_connections.id"),
            nullable=True,
        ),
        sa.Column("external_session_id", sa.String(length=255), nullable=True),
        sa.Column("event_seq", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column(
            "started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_agent_sessions_company_id", "agent_sessions", ["company_id"])
    op.create_index(
        "ix_agent_sessions_company_agent_activity",
        "agent_sessions",
        ["company_id", "agent_id", "last_activity_at"],
    )
    op.create_index(
        "ix_agent_sessions_company_workspace", "agent_sessions", ["company_id", "workspace_id"]
    )
    op.create_index("ix_agent_sessions_company_status", "agent_sessions", ["company_id", "status"])

    if is_pg:
        op.execute("ALTER TABLE agent_sessions ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE agent_sessions FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON agent_sessions "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON agent_sessions;")
        op.execute("ALTER TABLE agent_sessions NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE agent_sessions DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_agent_sessions_company_status", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_company_workspace", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_company_agent_activity", table_name="agent_sessions")
    op.drop_index("ix_agent_sessions_company_id", table_name="agent_sessions")
    op.drop_table("agent_sessions")
