"""memory evidence: append-only evidence and the idempotency ledger

Revision ID: b4d9f2a61c73
Revises: e7a1c2d3f408
Create Date: 2026-10-02

Two tenant tables, ``memory_evidence`` and ``memory_operations``, with the same FORCE
``tenant_isolation`` row-level security as the other tenant tables (PostgreSQL only).
Both are append-only: a trigger refuses UPDATE and DELETE on PostgreSQL and SQLite, and
every foreign key is RESTRICT. A second trigger refuses an INSERT whose memory belongs to
another company (a foreign key alone cannot say that). ``memory_records`` rows and their
constraints are not touched; this revision only adds.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "b4d9f2a61c73"
down_revision: str | None = "e7a1c2d3f408"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("memory_evidence", "memory_operations")
_TENANT_PREDICATE = "company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid"
_FUNCTION = "memory_evidence_append_only"
_SAME_COMPANY = "memory_evidence_same_company"
# Frozen copies of the model vocabularies; a later revision changes them with its own constraint.
_KINDS = ("human_attestation", "chat_turn", "tool_invocation", "task_attempt")
_SOURCES = ("user", "chat_turn", "tool_invocation", "task_attempt")
_GRADES = ("none", "assert", "verify")
_OPERATIONS = ("attach_evidence", "accept_candidate", "assert_trust", "verify_trust")


def _s(n: int) -> sqlmodel.sql.sqltypes.AutoString:
    return sqlmodel.sql.sqltypes.AutoString(length=n)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    uid = sa.Uuid()

    def company() -> sa.ForeignKey:
        return sa.ForeignKey("companies.id", ondelete="RESTRICT")

    def memory() -> sa.ForeignKey:
        return sa.ForeignKey("memory_records.id", ondelete="RESTRICT")

    op.create_table(
        "memory_evidence",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, company(), nullable=False),
        sa.Column("memory_id", uid, memory(), nullable=False),
        sa.Column("evidence_kind", _s(30), nullable=False),
        sa.Column("source_type", _s(30), nullable=False),
        sa.Column("source_id", _s(64), nullable=False),
        sa.Column("reason_code", _s(40), nullable=False, server_default=""),
        sa.Column("grade", _s(10), nullable=False),
        sa.Column("source_digest", _s(64), nullable=False),
        sa.Column("policy_version", _s(40), nullable=False),
        sa.Column("idempotency_key", _s(128), nullable=False),
        sa.Column("created_by", _s(100), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "company_id", "memory_id", "source_type", "source_id", "reason_code",
            name="uq_memory_evidence_source",
        ),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_memory_evidence_idempotency"),
        sa.CheckConstraint(_in("evidence_kind", _KINDS), name="ck_memory_evidence_kind"),
        sa.CheckConstraint(_in("source_type", _SOURCES), name="ck_memory_evidence_source_type"),
        sa.CheckConstraint(_in("grade", _GRADES), name="ck_memory_evidence_grade"),
    )
    op.create_index(
        "ix_memory_evidence_company_memory", "memory_evidence", ["company_id", "memory_id"]
    )
    op.create_index(
        "ix_memory_evidence_company_source",
        "memory_evidence",
        ["company_id", "source_type", "source_id"],
    )
    op.create_table(
        "memory_operations",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, company(), nullable=False),
        sa.Column("memory_id", uid, memory(), nullable=False),
        sa.Column("operation", _s(30), nullable=False),
        sa.Column("idempotency_key", _s(128), nullable=False),
        sa.Column("request_digest", _s(64), nullable=False),
        sa.Column("actor", _s(100), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_memory_operations_key"),
        sa.CheckConstraint(_in("operation", _OPERATIONS), name="ck_memory_operations_operation"),
    )
    op.create_index(
        "ix_memory_operations_company_memory", "memory_operations", ["company_id", "memory_id"]
    )

    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        for table in _TABLES:
            for verb in ("UPDATE", "DELETE"):
                op.execute(
                    f"CREATE TRIGGER trg_{table}_no_{verb.lower()} BEFORE {verb} ON {table} "
                    f"BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END;"
                )
            op.execute(
                f"CREATE TRIGGER trg_{table}_same_company BEFORE INSERT ON {table} "
                f"WHEN NOT EXISTS (SELECT 1 FROM memory_records m "
                f"WHERE m.id = NEW.memory_id AND m.company_id = NEW.company_id) "
                f"BEGIN SELECT RAISE(ABORT, '{table} must reference a memory of its company'); END;"
            )
        return
    if dialect != "postgresql":
        return
    op.execute(
        f"CREATE FUNCTION {_FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN RAISE EXCEPTION 'memory evidence tables are append-only'; END; $$;"
    )
    op.execute(
        f"CREATE FUNCTION {_SAME_COMPANY}() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN IF NOT EXISTS (SELECT 1 FROM memory_records m "
        "WHERE m.id = NEW.memory_id AND m.company_id = NEW.company_id) THEN "
        "RAISE EXCEPTION 'memory evidence must reference a memory of its own company'; "
        "END IF; RETURN NEW; END; $$;"
    )
    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_FUNCTION}();"
        )
        op.execute(
            f"CREATE TRIGGER trg_{table}_same_company BEFORE INSERT ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {_SAME_COMPANY}();"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE});"
        )


def downgrade() -> None:
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table};")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_same_company ON {table};")
    elif dialect == "sqlite":
        for table in _TABLES:
            for verb in ("update", "delete"):
                op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_{verb};")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_same_company;")
    for table in reversed(_TABLES):
        op.drop_table(table)
    if dialect == "postgresql":
        op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION}();")
        op.execute(f"DROP FUNCTION IF EXISTS {_SAME_COMPANY}();")
