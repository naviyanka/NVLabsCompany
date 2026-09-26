"""link transcript, tool calls, spend, checkpoints and heartbeats to sessions (ws02)

Revision ID: d5e1a0c3b702
Revises: d5e1a0c3b701
Create Date: 2026-09-26

Adds a nullable session_id to chat_messages, tool_invocations, cost_events,
execution_checkpoints and heartbeat_runs. chat_messages also gains kind, seq
and payload so it can carry the whole session timeline without a second
event table; (session_id, seq) is unique. NULL session_id rows are allowed
(both dialects treat NULLs as distinct in a unique constraint), so pre-session
rows stay valid until ws03 backfills what can be safely attributed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1a0c3b702"
down_revision: str | None = "d5e1a0c3b701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Transcript rows die with their session; everything else just loses the link.
_LINKED = {
    "chat_messages": "CASCADE",
    "tool_invocations": "SET NULL",
    "cost_events": "SET NULL",
    "execution_checkpoints": "SET NULL",
    "heartbeat_runs": "SET NULL",
}


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    for table, ondelete in _LINKED.items():
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "session_id",
                    uuid_type,
                    # Named so SQLite batch mode can recreate the table.
                    sa.ForeignKey(
                        "agent_sessions.id", name=f"fk_{table}_session_id", ondelete=ondelete
                    ),
                    nullable=True,
                )
            )
            if table == "chat_messages":
                batch.add_column(
                    sa.Column(
                        "kind", sa.String(length=20), nullable=False, server_default="message"
                    )
                )
                batch.add_column(sa.Column("seq", sa.Integer(), nullable=True))
                batch.add_column(sa.Column("payload", sa.JSON(), nullable=True))
                batch.create_unique_constraint(
                    "uq_chat_messages_session_seq", ["session_id", "seq"]
                )
        op.create_index(f"ix_{table}_session_id", table, ["session_id"])


def downgrade() -> None:
    for table in reversed(list(_LINKED)):
        op.drop_index(f"ix_{table}_session_id", table_name=table)
        with op.batch_alter_table(table) as batch:
            if table == "chat_messages":
                batch.drop_constraint("uq_chat_messages_session_seq", type_="unique")
                batch.drop_column("payload")
                batch.drop_column("seq")
                batch.drop_column("kind")
            batch.drop_constraint(f"fk_{table}_session_id", type_="foreignkey")
            batch.drop_column("session_id")
