"""pgvector embeddings for knowledge_chunks

Adds the `vector` extension and converts knowledge_chunks.embedding_vector from
JSON to vector(1536) with an HNSW cosine index. SQLite dev databases keep the
JSON column (no extension, no index) — the model declares a JSON variant there.

Revision ID: d5b1f7a3c210
Revises: c9a1e2b73d40
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5b1f7a3c210"
down_revision: Union[str, None] = "c9a1e2b73d40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 1536


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite dev fallback: column stays JSON.

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # JSON arrays are not directly castable to vector; go through text.
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ALTER COLUMN embedding_vector TYPE vector(%d) "
        "USING CASE WHEN embedding_vector IS NULL THEN NULL "
        "ELSE embedding_vector::text::vector(%d) END" % (EMBEDDING_DIM, EMBEDDING_DIM)
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_hnsw "
        "ON knowledge_chunks USING hnsw (embedding_vector vector_cosine_ops)"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_hnsw")
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ALTER COLUMN embedding_vector TYPE json "
        "USING CASE WHEN embedding_vector IS NULL THEN NULL "
        "ELSE embedding_vector::text::json END"
    )
