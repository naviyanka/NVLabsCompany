"""add row level security to tenant tables

Revision ID: c4f7d2e91b50
Revises: b8e5f2a1c930
Create Date: 2026-09-09

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4f7d2e91b50'
down_revision: Union[str, None] = 'b8e5f2a1c930'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TENANT_TABLES = [
    "tasks",
    "agents",
    "budget_policies",
    "goals",
    "projects",
    "approvals",
    "audit_log",
    "knowledge_chunks",
    "knowledge_pages",
]

def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
            op.execute(
                f"CREATE POLICY tenant_isolation ON {table} "
                f"USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
                f"WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
            )

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TENANT_TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
            op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;")
            op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")
