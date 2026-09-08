"""explicit polymorphic parent for knowledge_chunks

ADR 0002 §12, Option B. Migration c2f9a4d81b70 dropped the single-target FK so a
chunk could belong to either a knowledge_pages row or an obsidian_documents row,
but left the parent's identity implicit in a column still called ``page_id``. A
reader could not tell which table a given chunk pointed at.

This makes the pair explicit: ``page_id`` becomes ``source_id``, and a new
``source_type`` names the parent table.

Every existing chunk is a knowledge-page chunk, so the server_default backfills
them to 'knowledge_page' in the same statement that adds the column — no row is
orphaned and no parent identity changes, since source_id keeps the exact UUID
page_id held.

Revision ID: d8e3b6c04a90
Revises: c2f9a4d81b70
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "d8e3b6c04a90"
down_revision: Union[str, None] = "c2f9a4d81b70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KNOWLEDGE_PAGE = "knowledge_page"


def upgrade() -> None:
    # server_default backfills existing rows as it adds the column; every chunk
    # that exists today belongs to a knowledge page.
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "source_type",
            sa.String(length=32),
            nullable=False,
            server_default=_KNOWLEDGE_PAGE,
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_source_type", "knowledge_chunks", ["source_type"]
    )

    # Rename rather than add-and-copy: the UUID values are unchanged, so a rename
    # preserves every parent identity with no data movement and no window where a
    # chunk has no parent. batch_alter_table so SQLite (which cannot rename a
    # column in place on older versions) is handled by table recreation.
    op.drop_index("ix_knowledge_chunks_page_id", table_name="knowledge_chunks")
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.alter_column("page_id", new_column_name="source_id")
    op.create_index(
        "ix_knowledge_chunks_source_id", "knowledge_chunks", ["source_id"]
    )
    # The lookup Phase 1B actually runs is "every chunk of this parent", which is
    # (source_type, source_id) — a composite serves it in one index scan.
    op.create_index(
        "ix_knowledge_chunks_source",
        "knowledge_chunks",
        ["source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_chunks_source", table_name="knowledge_chunks")
    op.drop_index("ix_knowledge_chunks_source_id", table_name="knowledge_chunks")
    with op.batch_alter_table("knowledge_chunks") as batch:
        batch.alter_column("source_id", new_column_name="page_id")
    op.create_index(
        "ix_knowledge_chunks_page_id", "knowledge_chunks", ["page_id"]
    )

    op.drop_index("ix_knowledge_chunks_source_type", table_name="knowledge_chunks")
    op.drop_column("knowledge_chunks", "source_type")
    # Vault-derived chunks survive this downgrade as rows whose page_id points at
    # a knowledge_pages row that does not exist. Dropping source_type is what
    # makes that undetectable, so downgrading past this revision with vault
    # chunks present is an irreversible-data boundary: delete them first.
