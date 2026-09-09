"""add llm_connections table + agents.connection_id + RLS

Revision ID: a1b2c3d4e5f6
Revises: f4a5b6c7d8e9
Create Date: 2026-09-09

WP-22b commit 1. Tenant-scoped inference endpoints. RLS mirrors the
tenant_isolation policy from c4f7d2e91b50 so a row created under one company
is invisible to another. The api_key_ref / mgmt_key_ref columns reference
secrets.id; the raw key is never stored here.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = 'f4a5b6c7d8e9'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "llm_connections",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("base_url", sa.String(length=1024), nullable=False),
        sa.Column("wire_format", sa.String(length=50), nullable=False),
        sa.Column("api_key_ref", sa.String(length=255), nullable=True),
        sa.Column("mgmt_key_ref", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_llm_connections_company_id", "llm_connections", ["company_id"])

    with op.batch_alter_table("agents") as batch:
        batch.add_column(
            sa.Column(
                "connection_id",
                uuid_type,
                sa.ForeignKey("llm_connections.id"),
                nullable=True,
            )
        )

    if is_pg:
        op.execute("ALTER TABLE llm_connections ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE llm_connections FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON llm_connections "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON llm_connections;")
        op.execute("ALTER TABLE llm_connections NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE llm_connections DISABLE ROW LEVEL SECURITY;")

    with op.batch_alter_table("agents") as batch:
        batch.drop_column("connection_id")

    op.drop_index("ix_llm_connections_company_id", table_name="llm_connections")
    op.drop_table("llm_connections")
