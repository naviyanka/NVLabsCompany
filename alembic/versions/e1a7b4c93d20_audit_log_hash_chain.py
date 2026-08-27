"""Add hash chain to audit_log, add audit_log_archive, guard against mutation.

Phase 0.1 — the audit log becomes the durable, verifiable record of what
happened. Three things change:

1. `audit_log` gains `sequence_number`, `entry_hash`, `previous_hash` so the
   SHA-256 chain built by `PersistentAuditLogger` survives a restart, plus
   `archived_at` so retention can mark a row without removing it.
   `company_id` becomes nullable — system-level events have no tenant.
2. `audit_log_archive` receives copies of rows past their retention age.
   Retention copies and stamps; it never deletes from the verified chain.
3. A DB-level guard rejects DELETE on `audit_log` and rejects any UPDATE that
   changes a chain-bearing column. `archived_at` is the single mutable
   column, because retention has to stamp it. Application code cannot bypass
   this: the check lives in the database, so a stray ORM update, a migration
   mistake, or a hand-typed UPDATE all fail the same way.

   Postgres also gets `REVOKE UPDATE, DELETE` on the table so the trigger is
   not the only line of defense. The revoke is deliberately non-fatal — on a
   managed instance where the migration role cannot alter grants, the trigger
   still holds.

Revision ID: e1a7b4c93d20
Revises: b4e44200443e
Create Date: 2026-08-26

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e1a7b4c93d20"
down_revision: Union[str, None] = "b4e44200443e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Columns that carry the chain. Changing any of them breaks verification, so
# the trigger rejects an UPDATE that touches them.
_IMMUTABLE = (
    "id",
    "company_id",
    "actor_type",
    "actor_id",
    "action",
    "resource_type",
    "resource_id",
    "details",
    "ip_address",
    "created_at",
    "sequence_number",
    "entry_hash",
    "previous_hash",
)

_SQLITE_GUARD_UPDATE = """
CREATE TRIGGER audit_log_no_update
BEFORE UPDATE ON audit_log
FOR EACH ROW
WHEN {conditions}
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: only archived_at may change');
END;
"""

_SQLITE_GUARD_DELETE = """
CREATE TRIGGER audit_log_no_delete
BEFORE DELETE ON audit_log
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only: DELETE is not permitted');
END;
"""

_PG_GUARD_FN = """
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'audit_log is append-only: DELETE is not permitted';
    END IF;
    IF (to_jsonb(OLD) - 'archived_at') IS DISTINCT FROM
       (to_jsonb(NEW) - 'archived_at') THEN
        RAISE EXCEPTION
            'audit_log is append-only: only archived_at may change';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _sqlite_update_conditions() -> str:
    """Build the trigger WHEN clause: true if any chain column changed.

    `IS NOT` is used rather than `<>` so a NULL on either side compares
    correctly — `NULL <> NULL` is NULL, which would let a nullable column be
    silently rewritten.
    """
    return " OR ".join(f"OLD.{col} IS NOT NEW.{col}" for col in _IMMUTABLE)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    with op.batch_alter_table("audit_log") as batch:
        batch.add_column(sa.Column("sequence_number", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "entry_hash",
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "previous_hash",
                sqlmodel.sql.sqltypes.AutoString(length=64),
                nullable=True,
            )
        )
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        # System-level events have no tenant.
        batch.alter_column("company_id", existing_type=sa.Uuid(), nullable=True)

    op.create_index(
        op.f("ix_audit_log_sequence_number"),
        "audit_log",
        ["sequence_number"],
        unique=True,
    )

    op.create_table(
        "audit_log_archive",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column(
            "actor_type", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.Column(
            "actor_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column(
            "action", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False
        ),
        sa.Column(
            "resource_type",
            sqlmodel.sql.sqltypes.AutoString(length=100),
            nullable=True,
        ),
        sa.Column(
            "resource_id", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True
        ),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column(
            "ip_address", sqlmodel.sql.sqltypes.AutoString(length=45), nullable=True
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=True),
        sa.Column(
            "entry_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column(
            "previous_hash", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
        sa.Column("archived_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_audit_log_archive_company_id"),
        "audit_log_archive",
        ["company_id"],
    )
    op.create_index(
        op.f("ix_audit_log_archive_sequence_number"),
        "audit_log_archive",
        ["sequence_number"],
    )

    if dialect == "sqlite":
        op.execute(
            _SQLITE_GUARD_UPDATE.format(conditions=_sqlite_update_conditions())
        )
        op.execute(_SQLITE_GUARD_DELETE)
    elif dialect == "postgresql":
        op.execute(_PG_GUARD_FN)
        op.execute(
            "CREATE TRIGGER audit_log_append_only "
            "BEFORE UPDATE OR DELETE ON audit_log "
            "FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();"
        )
        # Defense in depth. Non-fatal: some managed roles cannot alter grants.
        try:
            op.execute("REVOKE UPDATE, DELETE ON audit_log FROM PUBLIC;")
        except Exception:  # pragma: no cover - depends on deployment role
            pass


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_update;")
        op.execute("DROP TRIGGER IF EXISTS audit_log_no_delete;")
    elif dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_log_append_only ON audit_log;")
        op.execute("DROP FUNCTION IF EXISTS audit_log_append_only();")

    op.drop_index(
        op.f("ix_audit_log_archive_sequence_number"), table_name="audit_log_archive"
    )
    op.drop_index(
        op.f("ix_audit_log_archive_company_id"), table_name="audit_log_archive"
    )
    op.drop_table("audit_log_archive")

    op.drop_index(op.f("ix_audit_log_sequence_number"), table_name="audit_log")
    with op.batch_alter_table("audit_log") as batch:
        batch.alter_column("company_id", existing_type=sa.Uuid(), nullable=False)
        batch.drop_column("archived_at")
        batch.drop_column("previous_hash")
        batch.drop_column("entry_hash")
        batch.drop_column("sequence_number")
