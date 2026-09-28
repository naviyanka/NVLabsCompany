"""organization snapshots: immutable versions and per-company refresh state

Revision ID: e7a1c2d3f405
Revises: e7a1c2d3f404
Create Date: 2026-09-29

``organization_snapshots`` holds one immutable row per snapshot version of a
company; ``(company_id, version)`` and ``(company_id, generation_key)`` are
unique, so racing generations cannot create duplicate versions.
``organization_snapshot_state`` holds one row per company: dirty marks, the
generation lease and the last refresh error. Both are tenant tables under
row-level security on PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f405"
down_revision: str | None = "e7a1c2d3f404"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TENANT_TABLES = ("organization_snapshots", "organization_snapshot_state")


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "organization_snapshots",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("generation_key", sa.String(length=128), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("data_as_of", sa.DateTime(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("company_id", "version", name="uq_organization_snapshots_version"),
        sa.UniqueConstraint(
            "company_id", "generation_key", name="uq_organization_snapshots_generation"
        ),
    )
    op.create_table(
        "organization_snapshot_state",
        sa.Column(
            "company_id", uuid_type, sa.ForeignKey("companies.id"), primary_key=True
        ),
        sa.Column("dirty_since", sa.DateTime(), nullable=True),
        sa.Column("last_dirty_at", sa.DateTime(), nullable=True),
        sa.Column("generating_until", sa.DateTime(), nullable=True),
        sa.Column("generating_by", sa.String(length=64), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
    )

    if is_pg:
        for table in _TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
                "WITH CHECK "
                "(company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in _TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
    op.drop_table("organization_snapshot_state")
    op.drop_table("organization_snapshots")
