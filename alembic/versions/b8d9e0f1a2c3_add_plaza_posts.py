"""add plaza_posts table

Revision ID: b8d9e0f1a2c3
Revises: a2c4e6081357
Create Date: 2026-09-15

WP-23b: the PlazaPost model (src/nexus/models/plaza.py) shipped without a
migration — plaza_posts was absent from every migrated database (postgres
included). It only existed on dev SQLite DBs via metadata.create_all.
Columns mirror the model exactly.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d9e0f1a2c3'
down_revision: str | None = 'a2c4e6081357'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    uuid_type = postgresql.UUID(as_uuid=True) if is_pg else sa.Uuid()

    op.create_table(
        "plaza_posts",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column("company_id", uuid_type, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("agent_id", uuid_type, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("agent_name", sa.String(length=255), nullable=False),
        sa.Column("post_type", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("post_metadata", sa.JSON(), nullable=True),
        sa.Column("reactions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_plaza_posts_company_id", "plaza_posts", ["company_id"])
    op.create_index("ix_plaza_posts_agent_id", "plaza_posts", ["agent_id"])

    if is_pg:
        op.execute("ALTER TABLE plaza_posts ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE plaza_posts FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON plaza_posts "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON plaza_posts;")
        op.execute("ALTER TABLE plaza_posts NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE plaza_posts DISABLE ROW LEVEL SECURITY;")

    op.drop_index("ix_plaza_posts_agent_id", table_name="plaza_posts")
    op.drop_index("ix_plaza_posts_company_id", table_name="plaza_posts")
    op.drop_table("plaza_posts")
