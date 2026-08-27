"""Backfill embedding_vector for knowledge_chunks that have none.

Run after the pgvector migration:
    EMBEDDING_PROVIDER=openai python scripts/backfill_chunk_embeddings.py

Only chunks with a NULL embedding_vector are touched; re-running is safe.
"""

import asyncio
import sys

from sqlmodel import select

from nexus.database import async_session_factory
from nexus.knowledge.embeddings import get_embedding_provider
from nexus.models.knowledge import EMBEDDING_DIM, KnowledgeChunk

BATCH_SIZE = 100


async def backfill(batch_size: int = BATCH_SIZE) -> int:
    provider = get_embedding_provider()
    if provider is None:
        print("No embedding provider configured (set EMBEDDING_PROVIDER).", file=sys.stderr)
        return 0
    if getattr(provider, "dimension", EMBEDDING_DIM) != EMBEDDING_DIM:
        print(
            f"Provider dimension {provider.dimension} != column dimension {EMBEDDING_DIM}.",
            file=sys.stderr,
        )
        return 0

    total = 0
    async with async_session_factory() as db:
        while True:
            rows = (
                await db.exec(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.embedding_vector.is_(None))  # type: ignore[attr-defined]
                    .limit(batch_size)
                )
            ).all()
            if not rows:
                break

            vectors = await provider.embed_batch([c.content for c in rows])
            for chunk, vector in zip(rows, vectors):
                chunk.embedding_vector = vector
                db.add(chunk)
            await db.commit()

            total += len(rows)
            print(f"embedded {total} chunks")

    return total


if __name__ == "__main__":
    print(f"done: {asyncio.run(backfill())} chunks backfilled")
