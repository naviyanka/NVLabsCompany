"""row-level security on memory_records, obsidian_documents, vault_write_grants

Revision ID: e7a1c2d3f407
Revises: e7a1c2d3f406
Create Date: 2026-09-29

These three tables carry ``company_id`` but had no policy, so any session that
was not filtering by company could read or mutate every tenant's rows (the
orchestrator's memory maintenance did exactly that). They now get the same
``tenant_isolation`` policy as the other tenant tables, with FORCE so the table
owner is subject to it too. PostgreSQL only; SQLite has no RLS and is skipped.

Only ``system_session`` (BYPASSRLS role) can see across tenants afterwards.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f407"
down_revision: str | None = "e7a1c2d3f406"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = ("memory_records", "obsidian_documents", "vault_write_grants")

_TENANT_PREDICATE = "company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid"


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE});"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
