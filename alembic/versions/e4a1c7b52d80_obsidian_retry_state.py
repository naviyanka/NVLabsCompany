"""retry state for obsidian_documents

ADR 0002 §26 reliability. Indexing a note can fail transiently — an embedding
provider outage, a rate limit, a momentary database blip — and before this there
was no way to retry: ``index_stale`` only selects documents whose status is
``stale``, so a ``failed`` document with unchanged content was never picked up
again.

Three columns carry the whole policy: how many consecutive attempts have failed,
when the last one ran, and a client-safe reason. A row that reaches
``MAX_INDEX_ATTEMPTS`` stops being retried, which is what bounds the loop.

Existing rows backfill to 0 attempts, so every document already in the registry
is eligible for its full retry budget.

Revision ID: e4a1c7b52d80
Revises: d8e3b6c04a90
Create Date: 2026-08-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "e4a1c7b52d80"
down_revision: Union[str, None] = "d8e3b6c04a90"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "obsidian_documents",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "obsidian_documents", sa.Column("last_attempt_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "obsidian_documents",
        sa.Column("last_error", sa.String(length=500), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("obsidian_documents", "last_error")
    op.drop_column("obsidian_documents", "last_attempt_at")
    op.drop_column("obsidian_documents", "attempt_count")
