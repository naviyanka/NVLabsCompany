"""tool effects: durable ledger that keeps a recovered chat turn from repeating a write

Revision ID: c5e8a3b71d94
Revises: b4d9f2a61c73
Create Date: 2026-10-04

Three tenant tables with the same FORCE ``tenant_isolation`` row-level security as the other
tenant tables (PostgreSQL only):

- ``tool_effects``: one row per logical tool call. The identity is the durable slot (company,
  turn, round index, invocation index), unique per company, which is what makes a logical call
  claimable by exactly one worker. The row also records the tool name and argument digest it
  was claimed for. ``turn_id`` is deliberately not a foreign key: a chat turn is deleted with
  its session and the ledger must outlive it.
- ``tool_notifications``: one row per invocation whose notification was already sent, so a
  replay does not notify again.
- ``tool_bridge_slots``: maps an inbound MCP bridge client's ``Idempotency-Key`` to the next
  free ordinal of its turn, so a retry of one request reaches the same ledger slot from any
  process and two requests never share one. Unique per (company, turn, key) and per
  (company, turn, ordinal).

``tool_effects.turn_attempt`` records which execution of the turn first claimed a slot; a
recovered execution may replay those slots but may not open a new write beside them.

The company foreign keys are RESTRICT. Nothing else is touched: no existing table, constraint
or policy changes, and the memory tables are not involved. The tables are owned by the
migrator role like every other table; the application role only receives the default DML
privileges, never ownership.

Downgrade refuses while ``tool_effects`` or ``tool_notifications`` holds any row: the first is
the only record that a write already happened, the second the only record that a notice was
already sent, and a recovered turn could repeat either. The refusal deletes nothing. An
operator who accepts that loss sets ``NEXUS_DESTROY_TOOL_EFFECTS`` to ``destroy-ledger``; the
downgrade then logs a warning with the table row counts (never row contents) and drops all
three tables. An upgrade afterwards creates an empty ledger, and turns that were in flight must not
be recovered automatically (see ``docs/runbooks/tool-effect-recovery.md``).
"""

import logging
import os
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "c5e8a3b71d94"
down_revision: str | None = "b4d9f2a61c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tool_effects"
_NOTICES = "tool_notifications"
_SLOTS = "tool_bridge_slots"
# The explicit operator override that lets a downgrade destroy a non-empty ledger.
OVERRIDE_ENV = "NEXUS_DESTROY_TOOL_EFFECTS"
OVERRIDE_VALUE = "destroy-ledger"

logger = logging.getLogger("alembic.runtime.migration")
_TENANT_PREDICATE = "company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid"
# Frozen copies of the model vocabularies; a later revision changes them with its own constraint.
_CLASSES = ("idempotent_write", "non_idempotent_write")
_STATUSES = ("executing", "succeeded", "failed", "ambiguous", "manual_recovery_required")


def _s(n: int) -> sqlmodel.sql.sqltypes.AutoString:
    return sqlmodel.sql.sqltypes.AutoString(length=n)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    uid = sa.Uuid()
    op.create_table(
        _TABLE,
        sa.Column("id", uid, primary_key=True),
        sa.Column(
            "company_id", uid, sa.ForeignKey("companies.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("turn_id", uid, nullable=False),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("invocation_index", sa.Integer(), nullable=False),
        sa.Column("tool_name", _s(255), nullable=False),
        sa.Column("effect_class", _s(24), nullable=False),
        sa.Column("invocation_key", _s(64), nullable=False),
        sa.Column("arguments_digest", _s(64), nullable=False),
        sa.Column("turn_attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", _s(24), nullable=False),
        sa.Column("claim_token", _s(64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", _s(500), nullable=True),
        sa.Column("resolved_by", _s(100), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_reason", _s(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("company_id", "invocation_key", name="uq_tool_effects_key"),
        sa.CheckConstraint(_in("status", _STATUSES), name="ck_tool_effects_status"),
        sa.CheckConstraint(_in("effect_class", _CLASSES), name="ck_tool_effects_class"),
        sa.CheckConstraint("attempt_count >= 1", name="ck_tool_effects_attempts"),
        sa.CheckConstraint("turn_attempt >= 1", name="ck_tool_effects_turn_attempt"),
        sa.CheckConstraint("round_index >= -1", name="ck_tool_effects_round"),
        sa.CheckConstraint("invocation_index >= 0", name="ck_tool_effects_position"),
        sa.CheckConstraint(
            "status <> 'executing' OR (claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_tool_effects_executing_claim",
        ),
    )
    op.create_index("ix_tool_effects_company_turn", _TABLE, ["company_id", "turn_id"])
    op.create_index("ix_tool_effects_company_status", _TABLE, ["company_id", "status"])
    op.create_table(
        _NOTICES,
        sa.Column(
            "company_id",
            uid,
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("invocation_key", _s(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        _SLOTS,
        sa.Column(
            "company_id",
            uid,
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("turn_id", uid, primary_key=True),
        sa.Column("idempotency_key", _s(128), primary_key=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("tool_name", _s(255), nullable=False),
        sa.Column("arguments_digest", _s(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "turn_id", "ordinal", name="uq_tool_bridge_slots_ordinal"
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_tool_bridge_slots_ordinal"),
    )

    if op.get_bind().dialect.name != "postgresql":
        return
    for table in (_TABLE, _NOTICES, _SLOTS):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE});"
        )


def _count(bind: sa.engine.Connection, table: str) -> int:
    return int(bind.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar_one())


def downgrade() -> None:
    bind = op.get_bind()
    postgres = bind.dialect.name == "postgresql"
    tables = (_TABLE, _NOTICES, _SLOTS)
    if postgres:
        # FORCE row level security hides every row from a session with no tenant set, so the
        # table owner would count zero rows and wrongly pass. Lift FORCE for the counts; the
        # statements are transactional, and FORCE is restored below on refusal as well.
        for table in tables:
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
    counts = {table: _count(bind, table) for table in tables}
    if (counts[_TABLE] or counts[_NOTICES]) and os.environ.get(OVERRIDE_ENV) != OVERRIDE_VALUE:
        if postgres:
            for table in tables:
                op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        raise RuntimeError(
            f"Refusing to downgrade: {_TABLE} holds {counts[_TABLE]} row(s) and {_NOTICES} "
            f"holds {counts[_NOTICES]}. The first is the only record that those writes already "
            "happened and the second that those notices were already sent, so a recovered turn "
            "could repeat them. Nothing was deleted. To accept that loss deliberately, set "
            f"{OVERRIDE_ENV}={OVERRIDE_VALUE} and run the downgrade again."
        )
    if counts[_TABLE] or counts[_NOTICES]:
        logger.warning(
            "DESTRUCTIVE DOWNGRADE: dropping %s (%d row(s)), %s (%d row(s)) and %s (%d row(s)). "
            "Replay protection for those calls is LOST; do not automatically recover any turn "
            "that was in flight.",
            _TABLE, counts[_TABLE], _NOTICES, counts[_NOTICES], _SLOTS, counts[_SLOTS],
        )
    if postgres:
        for table in (_SLOTS, _NOTICES, _TABLE):
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
    op.drop_table(_SLOTS)
    op.drop_table(_NOTICES)
    op.drop_table(_TABLE)
