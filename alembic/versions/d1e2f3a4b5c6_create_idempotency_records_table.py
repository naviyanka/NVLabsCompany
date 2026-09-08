"""create idempotency_records table

Revision ID: d1e2f3a4b5c6
Revises: c4f7d2e91b50
Create Date: 2026-09-09

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
import sqlmodel

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c4f7d2e91b50'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'idempotency_records',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('idem_key', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('endpoint', sqlmodel.sql.sqltypes.AutoString(length=512), nullable=False),
        sa.Column('request_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('response_body', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('state', sqlmodel.sql.sqltypes.AutoString(length=32), nullable=False, server_default='in_flight'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', 'idem_key', name='uq_idempotency_company_key')
    )
    op.create_index(op.f('ix_idempotency_records_company_id'), 'idempotency_records', ['company_id'], unique=False)
    op.create_index(op.f('ix_idempotency_records_idem_key'), 'idempotency_records', ['idem_key'], unique=False)

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE idempotency_records FORCE ROW LEVEL SECURITY;")
        op.execute(
            "CREATE POLICY tenant_isolation ON idempotency_records "
            "USING (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid) "
            "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid);"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON idempotency_records;")
        op.execute("ALTER TABLE idempotency_records NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE idempotency_records DISABLE ROW LEVEL SECURITY;")

    op.drop_index(op.f('ix_idempotency_records_idem_key'), table_name='idempotency_records')
    op.drop_index(op.f('ix_idempotency_records_company_id'), table_name='idempotency_records')
    op.drop_table('idempotency_records')
