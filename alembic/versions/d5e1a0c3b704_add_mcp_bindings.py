"""add mcp_bindings; converge MCP calls on tool_invocations (ws05)

Revision ID: d5e1a0c3b704
Revises: d5e1a0c3b703
Create Date: 2026-09-26

mcp_bindings grants an agent (or one session) access to a ToolConnection.
tool_invocations becomes the single audit store for every tool call:
tool_id turns nullable (MCP catalog tools and adapter-native tools are not rows
in ``tools``), and each row records the access-check outcome in
``authorization`` (allowed / would_deny / denied) plus ``authorization_detail``.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1a0c3b704"
down_revision: str | None = "d5e1a0c3b703"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "mcp_bindings",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "connection_id",
            uuid_type,
            sa.ForeignKey("tool_connections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=10), nullable=False),
        sa.Column(
            "agent_id", uuid_type, sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "session_id",
            uuid_type,
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("disabled_tools", sa.JSON(), nullable=False),
        sa.Column("instructions", sa.String(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column(
            "approval_id",
            uuid_type,
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint(
            "(target_type = 'agent' AND agent_id IS NOT NULL AND session_id IS NULL)"
            " OR (target_type = 'session' AND session_id IS NOT NULL AND agent_id IS NULL)",
            name="ck_mcp_bindings_target",
        ),
        sa.UniqueConstraint("agent_id", "connection_id", name="uq_mcp_bindings_agent_connection"),
        sa.UniqueConstraint(
            "session_id", "connection_id", name="uq_mcp_bindings_session_connection"
        ),
    )
    op.create_index("ix_mcp_bindings_company_id", "mcp_bindings", ["company_id"])
    op.create_index("ix_mcp_bindings_session_id", "mcp_bindings", ["session_id"])
    op.create_index("ix_mcp_bindings_company_agent", "mcp_bindings", ["company_id", "agent_id"])

    if is_pg:
        op.execute("ALTER TABLE mcp_bindings ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE mcp_bindings FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON mcp_bindings "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )

    with op.batch_alter_table("tool_invocations") as batch:
        batch.alter_column("tool_id", existing_type=uuid_type, nullable=True)
        batch.add_column(sa.Column("authorization", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("authorization_detail", sa.JSON(), nullable=True))
    op.create_index(
        "ix_tool_invocations_authorization", "tool_invocations", ["authorization"]
    )


def downgrade() -> None:
    op.drop_index("ix_tool_invocations_authorization", table_name="tool_invocations")
    with op.batch_alter_table("tool_invocations") as batch:
        batch.drop_column("authorization_detail")
        batch.drop_column("authorization")
    # tool_id stays nullable: restoring NOT NULL would require deleting the MCP
    # and adapter-native invocation rows, and those are audit records.

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON mcp_bindings;")
        op.execute("ALTER TABLE mcp_bindings NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE mcp_bindings DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_mcp_bindings_company_agent", table_name="mcp_bindings")
    op.drop_index("ix_mcp_bindings_session_id", table_name="mcp_bindings")
    op.drop_index("ix_mcp_bindings_company_id", table_name="mcp_bindings")
    op.drop_table("mcp_bindings")
