"""add agent_worktrees (P6.2)

Revision ID: d5e1a0c3b706
Revises: d5e1a0c3b705
Create Date: 2026-09-26

agent_worktrees records one agent's git worktree and branch in a connected
repository. Only the table is added here; nothing creates rows yet.

- (repository_id, branch) is unique across every row, archived included: an
  unmerged branch is never deleted, so its name stays taken in git.
- A session holds at most one created/active worktree (partial unique index).
- repository_id and agent_id are RESTRICT, so a repository or agent that owns
  worktrees cannot be deleted out from under them. session, task and approval
  are SET NULL: those links are history, not ownership.
- Cross-table company consistency is not a database constraint; PostgreSQL
  row-level security confines each row to the current company.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1a0c3b706"
down_revision: str | None = "d5e1a0c3b705"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_HOLDING_WHERE = sa.text("session_id IS NOT NULL AND status IN ('created', 'active')")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "agent_worktrees",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "repository_id",
            uuid_type,
            sa.ForeignKey("repositories.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "agent_id", uuid_type, sa.ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "session_id",
            uuid_type,
            sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "task_id", uuid_type, sa.ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("base_ref", sa.String(length=255), nullable=False),
        sa.Column("base_commit", sa.String(length=64), nullable=False),
        sa.Column("head_commit", sa.String(length=64), nullable=True),
        sa.Column("merged_commit", sa.String(length=64), nullable=True),
        sa.Column(
            "approval_id",
            uuid_type,
            sa.ForeignKey("approvals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("relative_path", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="created"),
        sa.Column("created_by", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint(
            "status IN ('created', 'active', 'review', 'approved', 'merged', 'archived')",
            name="ck_agent_worktrees_status",
        ),
        sa.UniqueConstraint("repository_id", "branch", name="uq_agent_worktrees_repository_branch"),
    )
    op.create_index("ix_agent_worktrees_company_id", "agent_worktrees", ["company_id"])
    op.create_index("ix_agent_worktrees_session_id", "agent_worktrees", ["session_id"])
    op.create_index(
        "ix_agent_worktrees_company_status", "agent_worktrees", ["company_id", "status"]
    )
    op.create_index(
        "ix_agent_worktrees_company_agent", "agent_worktrees", ["company_id", "agent_id"]
    )
    op.create_index(
        "uq_agent_worktrees_session_holding",
        "agent_worktrees",
        ["session_id"],
        unique=True,
        sqlite_where=_HOLDING_WHERE,
        postgresql_where=_HOLDING_WHERE,
    )

    if is_pg:
        op.execute("ALTER TABLE agent_worktrees ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE agent_worktrees FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON agent_worktrees "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON agent_worktrees;")
        op.execute("ALTER TABLE agent_worktrees NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE agent_worktrees DISABLE ROW LEVEL SECURITY;")

    op.drop_index("uq_agent_worktrees_session_holding", table_name="agent_worktrees")
    op.drop_index("ix_agent_worktrees_company_agent", table_name="agent_worktrees")
    op.drop_index("ix_agent_worktrees_company_status", table_name="agent_worktrees")
    op.drop_index("ix_agent_worktrees_session_id", table_name="agent_worktrees")
    op.drop_index("ix_agent_worktrees_company_id", table_name="agent_worktrees")
    op.drop_table("agent_worktrees")
