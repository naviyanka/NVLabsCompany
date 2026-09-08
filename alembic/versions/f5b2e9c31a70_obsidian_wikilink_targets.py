"""wikilink targets for obsidian_documents

ADR 0002 §14. Wikilinks are the vault's own relationship mechanism, so the
targets a note links to are parsed during indexing and stored on the document
row. Edges themselves stay derive-on-read (``api/routes/memory_graph.py``) — this
column exists so deriving them is a query against the registry rather than a
re-read of every note on disk.

The link text a human wrote is kept, not resolved ids: a link may name a note
that does not exist yet, and that dangling state is shown in the graph rather
than dropped.

Existing rows backfill to NULL and pick up their targets on the next index pass,
which their unchanged ``index_status`` already schedules.

Revision ID: f5b2e9c31a70
Revises: e4a1c7b52d80
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "f5b2e9c31a70"
down_revision: Union[str, None] = "e4a1c7b52d80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "obsidian_documents",
        sa.Column("wikilink_targets", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("obsidian_documents", "wikilink_targets")
