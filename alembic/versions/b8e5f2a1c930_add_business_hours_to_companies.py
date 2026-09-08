"""add business hours to companies

Revision ID: b8e5f2a1c930
Revises: a7c4e9b2d610
Create Date: 2026-09-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b8e5f2a1c930'
down_revision: Union[str, None] = 'a7c4e9b2d610'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.add_column(sa.Column("business_hours_start", sa.Integer(), nullable=False, server_default="9"))
        batch.add_column(sa.Column("business_hours_end", sa.Integer(), nullable=False, server_default="17"))
        batch.add_column(sa.Column("business_days", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False, server_default="mon,tue,wed,thu,fri"))


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("business_days")
        batch.drop_column("business_hours_end")
        batch.drop_column("business_hours_start")
