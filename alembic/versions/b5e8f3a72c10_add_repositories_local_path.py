"""add repositories local_path column

Revision ID: b5e8f3a72c10
Revises: a3f7c2d91b40
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "b5e8f3a72c10"
down_revision: Union[str, None] = "a3f7c2d91b40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("repositories", sa.Column("local_path", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("repositories", "local_path")
