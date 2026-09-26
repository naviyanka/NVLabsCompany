"""backfill agent_sessions from existing chat history (ws03)

Revision ID: d5e1a0c3b703
Revises: d5e1a0c3b702
Create Date: 2026-09-26

Backfill rules (exact):

1. Only chat_messages rows with session_id IS NULL are considered.
2. A row is associable only if its agent still exists AND that agent belongs
   to the same company as the row. Rows whose agent is gone, or whose
   company_id disagrees with the agent's, are left with session_id NULL.
   They cannot be attributed safely and are logged by count, not guessed at.
3. Associable rows are grouped by (company_id, agent_id, conversation_id).
   conversation_id NULL is its own group. Each group becomes one session.
   Before sessions existed, the chat route kept exactly one rolling
   conversation per agent, so for NULL conversation_id this is the
   relationship the old code actually had, not an invented one.
4. Each backfilled session is written with:
   - status 'idle'
   - adapter_type 'unknown' and model NULL
   - title NULL and created_by NULL
   - started_at / last_activity_at = min / max created_at of the group
   - event_seq = the group's row count
   - metadata {"legacy": true, "backfill": "ws03"}, plus
     "legacy_conversation_id" when the group had one
   The historical adapter and model are not recoverable (the agent's
   current values may have changed since), so none are fabricated.
5. seq is assigned 1..n within a group, ordered by (created_at, id).
   Ties on created_at are broken by id, which is deterministic but carries no
   meaning. The true insertion order of same-timestamp rows is not
   recoverable.
6. model_used, tokens_used, sender and text are never touched. kind keeps its
   ws02 server default 'message'.
7. tool_invocations, cost_events, execution_checkpoints and heartbeat_runs
   are NOT backfilled. They have no stored relationship to a conversation, and
   linking them by time proximity would invent history.

Downgrade reverses exactly this: it clears session_id/seq on rows pointing
at sessions whose metadata carries backfill == "ws03", then deletes those
sessions. Sessions created after the upgrade are untouched.
"""

import logging
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e1a0c3b703"
down_revision: str | None = "d5e1a0c3b702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

BACKFILL_TAG = "ws03"

_agents = sa.table("agents", sa.column("id", sa.Uuid()), sa.column("company_id", sa.Uuid()))
_messages = sa.table(
    "chat_messages",
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
    sa.column("agent_id", sa.Uuid()),
    sa.column("conversation_id", sa.String()),
    sa.column("created_at", sa.DateTime()),
    sa.column("session_id", sa.Uuid()),
    sa.column("seq", sa.Integer()),
)
_sessions = sa.table(
    "agent_sessions",
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
    sa.column("agent_id", sa.Uuid()),
    sa.column("status", sa.String()),
    sa.column("adapter_type", sa.String()),
    sa.column("event_seq", sa.BigInteger()),
    sa.column("metadata", sa.JSON()),
    sa.column("started_at", sa.DateTime()),
    sa.column("last_activity_at", sa.DateTime()),
)


def upgrade() -> None:
    bind = op.get_bind()

    unowned = bind.execute(
        sa.select(sa.func.count())
        .select_from(_messages.outerjoin(_agents, _agents.c.id == _messages.c.agent_id))
        .where(_messages.c.session_id.is_(None))
        .where(sa.or_(_agents.c.id.is_(None), _agents.c.company_id != _messages.c.company_id))
    ).scalar_one()
    if unowned:
        logger.warning(
            "ws03: %d chat_messages rows left unassociated (agent missing or cross-company)",
            unowned,
        )

    rows = bind.execute(
        sa.select(
            _messages.c.id,
            _messages.c.company_id,
            _messages.c.agent_id,
            _messages.c.conversation_id,
            _messages.c.created_at,
        )
        .select_from(_messages.join(_agents, _agents.c.id == _messages.c.agent_id))
        .where(_messages.c.session_id.is_(None))
        .where(_agents.c.company_id == _messages.c.company_id)
        .order_by(_messages.c.created_at, _messages.c.id)
    ).all()

    groups: dict[tuple, list] = {}
    for row in rows:
        groups.setdefault((row.company_id, row.agent_id, row.conversation_id), []).append(row)

    # ponytail: one UPDATE per message row; fine for chat-history volumes,
    # switch to an UPDATE ... FROM with ROW_NUMBER() if a tenant has millions.
    for (company_id, agent_id, conversation_id), members in groups.items():
        session_id = uuid.uuid4()
        metadata = {"legacy": True, "backfill": BACKFILL_TAG}
        if conversation_id is not None:
            metadata["legacy_conversation_id"] = conversation_id
        bind.execute(
            _sessions.insert().values(
                id=session_id,
                company_id=company_id,
                agent_id=agent_id,
                status="idle",
                adapter_type="unknown",
                event_seq=len(members),
                metadata=metadata,
                started_at=members[0].created_at,
                last_activity_at=members[-1].created_at,
            )
        )
        bind.execute(
            _messages.update()
            .where(_messages.c.id == sa.bindparam("mid"))
            .values(session_id=sa.bindparam("sid"), seq=sa.bindparam("n")),
            [{"mid": m.id, "sid": session_id, "n": n} for n, m in enumerate(members, start=1)],
        )


def downgrade() -> None:
    bind = op.get_bind()
    backfilled = [
        row.id
        for row in bind.execute(sa.select(_sessions.c.id, _sessions.c.metadata)).all()
        if isinstance(row.metadata, dict) and row.metadata.get("backfill") == BACKFILL_TAG
    ]
    for chunk_start in range(0, len(backfilled), 500):
        chunk = backfilled[chunk_start : chunk_start + 500]
        bind.execute(
            _messages.update()
            .where(_messages.c.session_id.in_(chunk))
            .values(session_id=None, seq=None)
        )
        bind.execute(_sessions.delete().where(_sessions.c.id.in_(chunk)))
