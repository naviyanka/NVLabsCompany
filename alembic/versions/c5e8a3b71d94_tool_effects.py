"""tool effects: durable ledger that keeps a recovered chat turn from repeating a write

Revision ID: c5e8a3b71d94
Revises: b4d9f2a61c73
Create Date: 2026-10-04

One tenant table, ``tool_effects``, with the same FORCE ``tenant_isolation`` row-level security
as the other tenant tables (PostgreSQL only). The company foreign key is RESTRICT and the
table is unique per (company, invocation key), which is what makes a logical tool call
claimable by exactly one worker. ``turn_id`` is deliberately not a foreign key: a chat turn
is deleted with its session and the ledger must outlive it. Nothing else is touched: no
existing table, constraint or policy changes, and the memory tables are not involved.

The ledger is owned by the migrator role like every other table; the application role only
receives the default DML privileges, never ownership.

Downgrade drops ``tool_effects`` and so permanently deletes every recorded effect, including
rows in ``manual_recovery_required``. Do not downgrade while any such row is open: after the
table is recreated a recovered turn can run the same non-idempotent tool a second time.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "c5e8a3b71d94"
down_revision: str | None = "b4d9f2a61c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tool_effects"
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
        sa.Column("tool_name", _s(255), nullable=False),
        sa.Column("effect_class", _s(24), nullable=False),
        sa.Column("invocation_key", _s(64), nullable=False),
        sa.Column("arguments_digest", _s(64), nullable=False),
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
        sa.CheckConstraint(
            "status <> 'executing' OR (claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_tool_effects_executing_claim",
        ),
    )
    op.create_index("ix_tool_effects_company_turn", _TABLE, ["company_id", "turn_id"])
    op.create_index("ix_tool_effects_company_status", _TABLE, ["company_id", "status"])

    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {_TABLE} "
        f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE});"
    )


def downgrade() -> None:
    # DATA LOSS: every ledger row is deleted, open manual-recovery rows included.
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {_TABLE};")
    op.drop_table(_TABLE)
