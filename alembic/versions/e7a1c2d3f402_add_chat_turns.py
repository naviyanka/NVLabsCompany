"""add chat_turns: durable employee chat turns

Revision ID: e7a1c2d3f402
Revises: e7a1c2d3f401
Create Date: 2026-09-27

One row per user prompt to an employee. The row, not the HTTP request, owns
the execution: any API worker claims a queued turn with a conditional UPDATE,
holds it under a renewable lease, and a recovery sweep requeues or fails turns
whose lease expired. See nexus.models.chat_turn and nexus.runtime.chat_turns.

- (company_id, session_id, idempotency_key) is unique: a retried request
  attaches to its turn instead of storing the prompt twice.
- (session_id, turn_seq) is unique; turn_seq is the prompt message's seq.
- Claim and sweep scans use (status, queued_at) and (status, lease_expires_at).
- PostgreSQL row-level security confines each row to the current company.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f402"
down_revision: str | None = "e7a1c2d3f401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATUSES = "'queued', 'claimed', 'running', 'completed', 'failed', 'cancelled', 'expired'"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "chat_turns",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column(
            "session_id",
            uuid_type,
            sa.ForeignKey("agent_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("turn_seq", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column(
            "prompt_message_id",
            uuid_type,
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "response_message_id",
            uuid_type,
            sa.ForeignKey("chat_messages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("execution_id", sa.String(length=64), nullable=True),
        sa.Column("adapter_used", sa.String(length=100), nullable=True),
        sa.Column("backend_used", sa.String(length=100), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("claimed_by", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.String(length=255), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("queued_at", sa.DateTime(), nullable=False),
        sa.Column("claimed_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("execution_context", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_chat_turns_status"),
        sa.UniqueConstraint(
            "company_id", "session_id", "idempotency_key", name="uq_chat_turns_idempotency"
        ),
        sa.UniqueConstraint("session_id", "turn_seq", name="uq_chat_turns_session_seq"),
    )
    op.create_index("ix_chat_turns_company_id", "chat_turns", ["company_id"])
    op.create_index("ix_chat_turns_agent_id", "chat_turns", ["agent_id"])
    op.create_index("ix_chat_turns_status_queued", "chat_turns", ["status", "queued_at"])
    op.create_index("ix_chat_turns_status_lease", "chat_turns", ["status", "lease_expires_at"])
    op.create_index(
        "ix_chat_turns_company_session_status",
        "chat_turns",
        ["company_id", "session_id", "status"],
    )

    if is_pg:
        op.execute("ALTER TABLE chat_turns ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE chat_turns FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON chat_turns "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON chat_turns;")
        op.execute("ALTER TABLE chat_turns NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE chat_turns DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_chat_turns_company_session_status", table_name="chat_turns")
    op.drop_index("ix_chat_turns_status_lease", table_name="chat_turns")
    op.drop_index("ix_chat_turns_status_queued", table_name="chat_turns")
    op.drop_index("ix_chat_turns_agent_id", table_name="chat_turns")
    op.drop_index("ix_chat_turns_company_id", table_name="chat_turns")
    op.drop_table("chat_turns")
