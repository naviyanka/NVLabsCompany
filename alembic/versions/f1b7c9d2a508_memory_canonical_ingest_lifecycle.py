"""canonical ingest and lifecycle columns on memory_records

Revision ID: f1b7c9d2a508
Revises: e7a1c2d3f407
Create Date: 2026-09-30

Adds first-class provenance, trust, lifecycle and idempotency columns, and
backfills every existing row deterministically. Nothing is rewritten, merged or
deleted: content is untouched, ``content_hash`` is the SHA-256 of the stored
content, and each legacy row gets the stable ingestion key ``legacy:<id>``.
Source fields are filled only where the row's own metadata names a real source;
no source id is invented.

memory_records is under FORCE row-level security on PostgreSQL, so the backfill
(which spans tenants) disables RLS on that one table for the duration of this
transaction and turns it back on, forced, before the migration ends. The
``tenant_isolation`` policy itself is never touched. SQLite has no RLS.
"""

import hashlib
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1b7c9d2a508"
down_revision: str | None = "e7a1c2d3f407"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "memory_records"
# Frozen copies: a migration must not change when the application vocabulary does.
_STATUSES = ("candidate", "active", "archived", "superseded", "rejected")
_TRUST = ("untrusted", "asserted", "verified")
_TYPES = (
    "fact", "preference", "decision", "directive", "lesson", "procedure", "risk", "error",
    "outcome", "summary", "delegation", "commitment", "hiring", "unknown",
)
_SCOPE_TYPES = {
    "guidelines": "directive",
    "system_rule": "directive",
    "episodic_reflection": "lesson",
    "l2_agent": "fact",
    "l3_shared": "fact",
}
_UNTRUSTED_MARK = "untrusted_candidate"
_BATCH = 500

_COLUMNS = (
    ("memory_type", sa.String(length=20), "unknown"),
    ("status", sa.String(length=20), "active"),
    ("trust_state", sa.String(length=20), "untrusted"),
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def _uuid_type(is_pg: bool):
    return postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()


def _short(value: object, limit: int) -> str | None:
    return value[:limit] if isinstance(value, str) and value.strip() else None


def _row_values(row, existing_target) -> dict:
    """The new column values for one legacy row, from its content and metadata only."""
    meta = row.meta if isinstance(row.meta, dict) else {}
    origin, trust, kind = meta.get("origin"), meta.get("trust"), meta.get("type")
    state = meta.get("status")

    status, trust_state = "active", "untrusted"
    if trust == _UNTRUSTED_MARK:
        status = "candidate"
    elif origin in ("api", "human") or trust == "operator_supplied":
        trust_state = "asserted"
    if row.scope == "executive":
        if state == "superseded":
            status = "superseded"
        elif state == "resolved":
            status = "archived"

    memory_type = kind if kind in _TYPES else _SCOPE_TYPES.get(row.scope, "unknown")

    source = meta.get("source") if isinstance(meta.get("source"), dict) else {}
    source_type = source_id = None
    for key, name in (("message_id", "chat_message"), ("turn_id", "chat_turn")):
        if _short(source.get(key), 128):
            source_type, source_id = name, source[key][:128]
            break
    else:
        # A bare {"type": ...} (chat extraction) names a source kind but no instance.
        source_type = _short(source.get("type"), 40)

    values = {
        "memory_type": memory_type,
        "status": status,
        "trust_state": trust_state,
        "source_type": source_type,
        "source_id": source_id,
        "content_hash": hashlib.sha256(row.content.encode()).hexdigest(),
        "ingestion_key": f"legacy:{row.id}",
        "supersedes_id": existing_target,
    }
    if status in ("superseded", "archived") and row.scope == "executive":
        values["lifecycle_changed_at"] = row.updated_at
        values["lifecycle_changed_by"] = "migration:f1b7c9d2a508"
    return values


def _backfill(bind, is_pg: bool) -> None:
    uid = _uuid_type(is_pg)
    t = sa.table(
        _TABLE,
        sa.column("id", uid),
        sa.column("company_id", uid),
        sa.column("scope", sa.String),
        sa.column("content", sa.Text),
        sa.column("metadata", sa.JSON),
        sa.column("updated_at", sa.DateTime),
        sa.column("memory_type", sa.String),
        sa.column("status", sa.String),
        sa.column("trust_state", sa.String),
        sa.column("source_type", sa.String),
        sa.column("source_id", sa.String),
        sa.column("content_hash", sa.String),
        sa.column("ingestion_key", sa.String),
        sa.column("supersedes_id", uid),
        sa.column("lifecycle_changed_at", sa.DateTime),
        sa.column("lifecycle_changed_by", sa.String),
    )
    last = None
    while True:
        query = sa.select(
            t.c.id,
            t.c.company_id,
            t.c.scope,
            t.c.content,
            t.c.metadata.label("meta"),
            t.c.updated_at,
        ).order_by(t.c.id).limit(_BATCH)
        if last is not None:
            query = query.where(t.c.id > last)
        rows = bind.execute(query).all()
        if not rows:
            return
        last = rows[-1].id
        for row in rows:
            meta = row.meta if isinstance(row.meta, dict) else {}
            target = None
            if row.scope == "executive" and isinstance(meta.get("supersedes"), str):
                try:
                    wanted = uuid.UUID(meta["supersedes"])
                except ValueError:
                    wanted = None
                # Same company only: a link across tenants is never created.
                if wanted is not None and wanted != row.id and bind.execute(
                    sa.select(t.c.id).where(t.c.id == wanted, t.c.company_id == row.company_id)
                ).first():
                    target = wanted
            bind.execute(
                t.update().where(t.c.id == row.id).values(**_row_values(row, target))
            )


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    if is_pg:
        op.execute(f"ALTER TABLE {_TABLE} DISABLE ROW LEVEL SECURITY;")

    with op.batch_alter_table(_TABLE) as batch:
        for name, type_, default in _COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        batch.add_column(sa.Column("source_type", sa.String(length=40), nullable=True))
        batch.add_column(sa.Column("source_id", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("source_created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("extractor_version", sa.String(length=40), nullable=True))
        batch.add_column(
            sa.Column("content_hash", sa.String(length=64), nullable=False, server_default="")
        )
        batch.add_column(
            sa.Column("ingestion_key", sa.String(length=80), nullable=False, server_default="")
        )
        batch.add_column(sa.Column("supersedes_id", _uuid_type(is_pg), nullable=True))
        batch.add_column(sa.Column("lifecycle_changed_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("lifecycle_changed_by", sa.String(length=100), nullable=True))

    _backfill(bind, is_pg)

    with op.batch_alter_table(_TABLE) as batch:
        # No ON DELETE action: a superseded row may not be deleted out from under its successor.
        batch.create_foreign_key(
            "fk_memory_records_supersedes_id", _TABLE, ["supersedes_id"], ["id"]
        )
        batch.create_unique_constraint(
            "uq_memory_records_ingestion", ["company_id", "ingestion_key"]
        )
        batch.create_check_constraint("ck_memory_records_status", _in("status", _STATUSES))
        batch.create_check_constraint("ck_memory_records_trust_state", _in("trust_state", _TRUST))
        batch.create_check_constraint("ck_memory_records_memory_type", _in("memory_type", _TYPES))
    op.create_index("ix_memory_records_supersedes_id", _TABLE, ["supersedes_id"])
    op.create_index(
        "ix_memory_records_company_scope_status",
        _TABLE,
        ["company_id", "scope", "status", "created_at"],
    )
    op.create_index(
        "ix_memory_records_company_source", _TABLE, ["company_id", "source_type", "source_id"]
    )

    if is_pg:
        op.execute(f"ALTER TABLE {_TABLE} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {_TABLE} FORCE ROW LEVEL SECURITY;")


def downgrade() -> None:
    op.drop_index("ix_memory_records_company_source", table_name=_TABLE)
    op.drop_index("ix_memory_records_company_scope_status", table_name=_TABLE)
    op.drop_index("ix_memory_records_supersedes_id", table_name=_TABLE)
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint("ck_memory_records_memory_type", type_="check")
        batch.drop_constraint("ck_memory_records_trust_state", type_="check")
        batch.drop_constraint("ck_memory_records_status", type_="check")
        batch.drop_constraint("uq_memory_records_ingestion", type_="unique")
        batch.drop_constraint("fk_memory_records_supersedes_id", type_="foreignkey")
        for name in (
            "lifecycle_changed_by", "lifecycle_changed_at", "supersedes_id", "ingestion_key",
            "content_hash", "extractor_version", "source_created_at", "source_id",
            "source_type", "trust_state", "status", "memory_type",
        ):
            batch.drop_column(name)
