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


_COLUMNS = [
    sa.Column("business_hours_start", sa.Integer(), nullable=False, server_default="9"),
    sa.Column("business_hours_end", sa.Integer(), nullable=False, server_default="17"),
    sa.Column("business_days", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False, server_default="mon,tue,wed,thu,fri"),
]


def upgrade() -> None:
    # Databases first built by create_all already have these columns.
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("companies")}
    with op.batch_alter_table("companies") as batch:
        for column in _COLUMNS:
            if column.name not in have:
                batch.add_column(column)


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch:
        batch.drop_column("business_days")
        batch.drop_column("business_hours_end")
        batch.drop_column("business_hours_start")
