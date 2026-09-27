"""add task_attempts, work_effects and tasks.work_spec

Revision ID: e7a1c2d3f403
Revises: e7a1c2d3f402
Create Date: 2026-09-28

A work task (one with a ``work_spec``) is executed through durable attempts.
Each ``task_attempts`` row is one try by an employee: its session, isolated
worktree, chat turn, structured report, artifact manifest and verification
result. See nexus.models.task_attempt and nexus.runtime.task_attempts.

- At most one active attempt per task (partial unique index).
- (task_id, attempt_number) is unique; a retry is the next number.
- (company_id, task_id, idempotency_key) is unique, so a repeated start
  request attaches to the attempt it created.
- ``work_effects`` is the side-effect ledger: (company_id, effect_key) is
  unique, so a retried commit, evidence write or notification is found rather
  than repeated.
- PostgreSQL row-level security confines both tables to the current company.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f403"
down_revision: str | None = "e7a1c2d3f402"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = (
    "'queued', 'claimed', 'running', 'verifying', 'completed', 'failed', "
    "'blocked', 'cancelled', 'expired'"
)
_ACTIVE_WHERE = sa.text("status IN ('queued', 'claimed', 'running', 'verifying')")
_EFFECT_KINDS = "'tool_invocation', 'file_write_batch', 'git_commit', 'pr_create', 'notification'"
_EFFECT_STATUSES = "'pending', 'done', 'failed'"

_TENANT_TABLES = ("task_attempts", "work_effects")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("work_spec", sa.JSON(), nullable=True))

    op.create_table(
        "task_attempts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "task_id", uuid_type, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column(
            "session_id",
            uuid_type,
            sa.ForeignKey("agent_sessions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "chat_turn_id",
            uuid_type,
            sa.ForeignKey("chat_turns.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column(
            "workspace_id",
            uuid_type,
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "repository_id",
            uuid_type,
            sa.ForeignKey("repositories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "worktree_id",
            uuid_type,
            sa.ForeignKey("agent_worktrees.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("recoveries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.String(length=255), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("context_snapshot", sa.JSON(), nullable=True),
        sa.Column("output_summary", sa.Text(), nullable=True),
        sa.Column("completion_reason", sa.String(length=32), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("report", sa.JSON(), nullable=True),
        sa.Column("report_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifacts", sa.JSON(), nullable=True),
        sa.Column("verification", sa.JSON(), nullable=True),
        sa.Column("usage", sa.JSON(), nullable=True),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_task_attempts_status"),
        sa.UniqueConstraint("task_id", "attempt_number", name="uq_task_attempts_task_number"),
        sa.UniqueConstraint(
            "company_id", "task_id", "idempotency_key", name="uq_task_attempts_idempotency"
        ),
    )
    op.create_index("ix_task_attempts_company_id", "task_attempts", ["company_id"])
    op.create_index("ix_task_attempts_agent_id", "task_attempts", ["agent_id"])
    op.create_index(
        "ix_task_attempts_status_lease", "task_attempts", ["status", "lease_expires_at"]
    )
    op.create_index("ix_task_attempts_company_task", "task_attempts", ["company_id", "task_id"])
    op.create_index(
        "uq_task_attempts_one_active",
        "task_attempts",
        ["task_id"],
        unique=True,
        sqlite_where=_ACTIVE_WHERE,
        postgresql_where=_ACTIVE_WHERE,
    )

    op.create_table(
        "work_effects",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column(
            "task_id", uuid_type, sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column(
            "attempt_id",
            uuid_type,
            sa.ForeignKey("task_attempts.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("effect_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(f"kind IN ({_EFFECT_KINDS})", name="ck_work_effects_kind"),
        sa.CheckConstraint(f"status IN ({_EFFECT_STATUSES})", name="ck_work_effects_status"),
        sa.UniqueConstraint("company_id", "effect_key", name="uq_work_effects_key"),
    )
    op.create_index("ix_work_effects_company_id", "work_effects", ["company_id"])
    op.create_index("ix_work_effects_company_task", "work_effects", ["company_id", "task_id"])

    if is_pg:
        for table in _TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
                "WITH CHECK "
                "(company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_work_effects_company_task", table_name="work_effects")
    op.drop_index("ix_work_effects_company_id", table_name="work_effects")
    op.drop_table("work_effects")

    op.drop_index("uq_task_attempts_one_active", table_name="task_attempts")
    op.drop_index("ix_task_attempts_company_task", table_name="task_attempts")
    op.drop_index("ix_task_attempts_status_lease", table_name="task_attempts")
    op.drop_index("ix_task_attempts_agent_id", table_name="task_attempts")
    op.drop_index("ix_task_attempts_company_id", table_name="task_attempts")
    op.drop_table("task_attempts")

    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("work_spec")
