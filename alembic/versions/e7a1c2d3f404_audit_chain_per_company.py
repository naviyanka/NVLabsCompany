"""audit_log: one hash chain per company

Revision ID: e7a1c2d3f404
Revises: e7a1c2d3f403
Create Date: 2026-09-28

The audit hash chain was global: ``sequence_number`` was unique across the
table and each row linked to the row before it, whichever company that row
belonged to. Under row-level security a writer only sees its own company's
rows, so it computed the next number from its own tail and collided with
other companies' numbers.

From this revision each company has its own chain (and events without a
company have one more): ``(company_id, sequence_number)`` is unique, and a
new row links to the previous row of the same company.

Existing rows cannot be relinked: the table is append-only and their hashes
cover the old links. Instead, each company that already has chained rows gets
one seal row appended to its chain:

- its ``previous_hash`` is a digest of that company's existing chained rows
  (sequence number and hash, in order), so changing, removing or adding any of
  them later is detected;
- its ``resource_id`` (which is hashed) says whether this migration found
  every existing chained row intact and linked to an earlier row. A chain that
  was already broken stays reported as broken rather than being laundered.

New rows for that company then link to the seal. Nothing is updated or
deleted, and the append-only triggers stay in place. On PostgreSQL the table
has FORCE ROW LEVEL SECURITY, which applies to the table owner too; it is
lifted for the duration of the backfill so the migration sees every company,
and restored afterwards.
"""

import hashlib
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f404"
down_revision: str | None = "e7a1c2d3f403"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHAINED = sa.text("sequence_number IS NOT NULL")

# Frozen copies of nexus.governance.audit_persistent: a migration must not
# change behaviour when the application code changes.
_SEALED = "audit.chain_sealed"
_INTACT = "legacy_intact"
_BROKEN = "legacy_broken"

_audit_log = sa.table(
    "audit_log",
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
    sa.column("actor_type", sa.String()),
    sa.column("actor_id", sa.String()),
    sa.column("action", sa.String()),
    sa.column("resource_type", sa.String()),
    sa.column("resource_id", sa.String()),
    sa.column("details", sa.JSON()),
    sa.column("created_at", sa.DateTime()),
    sa.column("sequence_number", sa.Integer()),
    sa.column("entry_hash", sa.String()),
    sa.column("previous_hash", sa.String()),
)


def _entry_hash(row: sa.Row | dict, previous_hash: str) -> str:
    """``compute_entry_hash`` over a row, with ``from_row``'s mapping."""
    r = row if isinstance(row, dict) else row._mapping
    hash_input = (
        f"{r['id']}|{r['actor_type']}|{r['actor_id'] or ''}|"
        f"{r['action']}|{r['resource_type']}|{r['resource_id']}|"
        f"{r['created_at'].isoformat()}|{r['company_id']}|"
        f"{previous_hash}"
    )
    return hashlib.sha256(hash_input.encode()).hexdigest()


def _legacy_digest(rows: list[sa.Row]) -> str:
    joined = "|".join(f"{r.sequence_number}:{r.entry_hash}" for r in rows)
    return hashlib.sha256(f"legacy-global-chain|{joined}".encode()).hexdigest()


def _seal_legacy_chains() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.select(_audit_log).where(_CHAINED).order_by(_audit_log.c.sequence_number)
    ).all()
    unchained = bind.execute(
        sa.select(_audit_log.c.company_id, sa.func.count())
        .where(_audit_log.c.sequence_number.is_(None))
        .group_by(_audit_log.c.company_id)
    ).all()

    # Rows written while RLS hid other companies' tails link to their own
    # company's previous row, rows written without RLS to the global previous
    # row. Either way an intact row matches its own hash and links to a row
    # that exists and came before it.
    seen = {"genesis"}
    intact = True
    for row in rows:
        if row.previous_hash not in seen or _entry_hash(row, row.previous_hash) != row.entry_hash:
            intact = False
        seen.add(row.entry_hash)

    by_company: dict[uuid.UUID | None, list[sa.Row]] = defaultdict(list)
    for row in rows:
        by_company[row.company_id].append(row)
    unchained_by_company = dict(unchained)

    now = datetime.now(UTC).replace(tzinfo=None)
    for company_id, legacy in by_company.items():
        seal = {
            "id": uuid.uuid4(),
            "company_id": company_id,
            "actor_type": "system",
            "actor_id": None,
            "action": _SEALED,
            "resource_type": "audit_chain",
            "resource_id": _INTACT if intact else _BROKEN,
            "details": {
                "migration": revision,
                "legacy_rows": len(legacy),
                "legacy_last_sequence": legacy[-1].sequence_number,
                "legacy_unchained_rows": unchained_by_company.get(company_id, 0),
            },
            "created_at": now,
            "sequence_number": legacy[-1].sequence_number + 1,
            "previous_hash": _legacy_digest(legacy),
        }
        seal["entry_hash"] = _entry_hash(seal, seal["previous_hash"])
        bind.execute(sa.insert(_audit_log).values(**seal))


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    if is_postgres:
        op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY;")

    op.drop_index("ix_audit_log_sequence_number", table_name="audit_log")
    op.create_index("ix_audit_log_sequence_number", "audit_log", ["sequence_number"])
    op.create_index(
        "uq_audit_log_company_sequence",
        "audit_log",
        ["company_id", "sequence_number"],
        unique=True,
        postgresql_nulls_not_distinct=True,
        postgresql_where=_CHAINED,
        sqlite_where=_CHAINED,
    )
    _seal_legacy_chains()

    if is_postgres:
        op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    # The seal rows stay: the table is append-only. Restoring the globally
    # unique sequence fails once two companies' chains share a number, which
    # is expected as soon as more than one company has written audit rows.
    op.drop_index("uq_audit_log_company_sequence", table_name="audit_log")
    op.drop_index("ix_audit_log_sequence_number", table_name="audit_log")
    op.create_index(
        "ix_audit_log_sequence_number", "audit_log", ["sequence_number"], unique=True
    )
