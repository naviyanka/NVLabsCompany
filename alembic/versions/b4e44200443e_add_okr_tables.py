"""add_okr_tables

Revision ID: b4e44200443e
Revises: c7d9e1f4a520
Create Date: 2026-08-26 20:02:23.893010

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b4e44200443e'
down_revision: Union[str, None] = 'c7d9e1f4a520'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('okr_objectives',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('description', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
    sa.Column('owner_agent_id', sa.Uuid(), nullable=True),
    sa.Column('time_frame', sqlmodel.sql.sqltypes.AutoString(length=100), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['owner_agent_id'], ['agents.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_okr_objectives_company_id'), 'okr_objectives', ['company_id'], unique=False)
    op.create_table('okr_key_results',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('objective_id', sa.Uuid(), nullable=False),
    sa.Column('company_id', sa.Uuid(), nullable=False),
    sa.Column('title', sqlmodel.sql.sqltypes.AutoString(length=500), nullable=False),
    sa.Column('target_value', sa.Float(), nullable=False),
    sa.Column('current_value', sa.Float(), nullable=False),
    sa.Column('unit', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('status', sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
    sa.ForeignKeyConstraint(['objective_id'], ['okr_objectives.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_okr_key_results_company_id'), 'okr_key_results', ['company_id'], unique=False)
    op.create_index(op.f('ix_okr_key_results_objective_id'), 'okr_key_results', ['objective_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_okr_key_results_objective_id'), table_name='okr_key_results')
    op.drop_index(op.f('ix_okr_key_results_company_id'), table_name='okr_key_results')
    op.drop_table('okr_key_results')
    op.drop_index(op.f('ix_okr_objectives_company_id'), table_name='okr_objectives')
    op.drop_table('okr_objectives')
