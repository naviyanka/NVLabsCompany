"""add columns the models gained without a migration

Revision ID: e7a1c2d3f401
Revises: d5e1a0c3b706
Create Date: 2026-09-27

Two model columns never got a migration, so a database built only by
``alembic upgrade head`` lacked them:

- ``agents.focus_items`` (JSON, added to the model in 0be6843). Every INSERT
  into ``agents`` names it, so the startup demo seed failed on a fresh
  database with "table agents has no column named focus_items".
- ``user_profiles.oidc_sub`` (VARCHAR(255), nullable).

Databases that were created with ``create_all`` or patched by hand may already
have them, so each column is added only when it is missing. The downgrade
drops them again.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7a1c2d3f401"
down_revision: str | None = "d5e1a0c3b706"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    ("agents", sa.Column("focus_items", sa.JSON(), nullable=True)),
    ("user_profiles", sa.Column("oidc_sub", sa.String(length=255), nullable=True)),
]


def _has_column(table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    for table, column in _COLUMNS:
        if not _has_column(table, column.name):
            op.add_column(table, column)


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        if _has_column(table, column.name):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column.name)
