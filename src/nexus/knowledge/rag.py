"""RAG Pipeline - Retrieval-Augmented Generation with chunking and hybrid search.

Provides document chunking, indexing, hybrid search (BM25 + vector similarity stub),
result reranking, and context assembly for use in agent prompts.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.memory.retriever import search as bm25_search, tokenize
from nexus.models.knowledge import KnowledgeChunk


class RAGPipeline:
    """Retrieval-Augmented Generation pipeline for knowledge retrieval.

    The RAG pipeline handles the full lifecycle of document retrieval:
    1. Chunking documents into indexable segments
    2. Storing chunks with metadata for later retrieval
    3. Hybrid search combining BM25 and vector similarity
    4. Reranking results by relevance heuristics
    5. Assembling a context window within token budgets

    Attributes:
        db: Async database session for persistence operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize RAGPipeline with a database session.

        Args:
            db: An async SQLAlchemy session for database operations.
        """
        self.db = db

    def chunk_document(
        self,
        content: str,
        strategy: str = "paragraph",
        chunk_size: int = 500,
    ) -> list[str]:
        """Split a document into chunks using the specified strategy.

        Supports multiple chunking strategies for different document types:
        - 'paragraph': Split on double newlines (best for prose)
        - 'section': Split on markdown headers (best for structured docs)
        - 'fixed_size': Split into fixed character-length chunks with overlap

        Args:
            content: The full document text to chunk.
            strategy: Chunking strategy - 'paragraph', 'section', or 'fixed_size'.
            chunk_size: Target chunk size in characters (used by 'fixed_size' strategy).

        Returns:
            List of chunk strings, preserving document order.

        Raises:
            ValueError: If an unsupported strategy is specified.
        """
        if strategy == "paragraph":
            return self._chunk_by_paragraph(content)
        elif strategy == "section":
            return self._chunk_by_section(content)
        elif strategy == "fixed_size":
            return self._chunk_by_fixed_size(content, chunk_size)
        else:
            raise ValueError(
                f"Unsupported chunking strategy: {strategy}. "
                f"Use 'paragraph', 'section', or 'fixed_size'."
            )

    def _chunk_by_paragraph(self, content: str) -> list[str]:
        """Split content on double newlines into paragraph chunks.

        Args:
            content: Text to split.

        Returns:
            Non-empty paragraph chunks.
        """
        paragraphs = re.split(r"\n\n+", content)
        return [p.strip() for p in paragraphs if p.strip()]

    def _chunk_by_section(self, content: str) -> list[str]:
        """Split content on markdown headers (lines starting with #).

        Each section includes its header line and all content until the next header.

        Args:
            content: Markdown text to split.

        Returns:
            Non-empty section chunks.
        """
        # Split on lines that start with one or more # characters
        sections = re.split(r"(?=^#+ )", content, flags=re.MULTILINE)
        return [s.strip() for s in sections if s.strip()]

    def _chunk_by_fixed_size(self, content: str, chunk_size: int) -> list[str]:
        """Split content into fixed-size character chunks with overlap.

        Uses a 10% overlap between chunks to preserve context at boundaries.

        Args:
            content: Text to split.
            chunk_size: Target size in characters for each chunk.

        Returns:
            Fixed-size chunks with overlap.
        """
        if not content:
            return []

        overlap = chunk_size // 10  # 10% overlap
        chunks: list[str] = []
        start = 0

        while start < len(content):
            end = start + chunk_size
            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end - overlap if end < len(content) else end

        return chunks

    async def index_chunks(
        self,
        company_id: uuid.UUID,
        page_id: uuid.UUID,
        chunks: list[str],
    ) -> list[KnowledgeChunk]:
        """Store document chunks as KnowledgeChunk records.

        Creates a KnowledgeChunk for each chunk string, preserving the
        chunk_index for ordering. Metadata includes the chunk length.

        Args:
            company_id: Company scope for the chunks.
            page_id: The knowledge page these chunks belong to.
            chunks: List of chunk content strings to store.

        Returns:
            List of created KnowledgeChunk instances.
        """
        records: list[KnowledgeChunk] = []
        for idx, chunk_content in enumerate(chunks):
            chunk_record = KnowledgeChunk(
                company_id=company_id,
                page_id=page_id,
                content=chunk_content,
                chunk_index=idx,
                metadata={"length": len(chunk_content)},
                created_at=datetime.now(timezone.utc),
            )
            self.db.add(chunk_record)
            records.append(chunk_record)

        await self.db.commit()
        for record in records:
            await self.db.refresh(record)
        return records

    async def search(
        self,
        company_id: uuid.UUID,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Perform hybrid search over knowledge chunks.

        Combines BM25 text search with optional vector similarity (stub).
        Results are returned with both scores for downstream reranking.

        Args:
            company_id: Company scope for the search.
            query: Search query string.
            top_k: Number of top results to return.

        Returns:
            List of dicts with keys: 'chunk', 'bm25_score', 'vector_score', 'combined_score'.
        """
        # Fetch all chunks for the company
        statement = select(KnowledgeChunk).where(
            KnowledgeChunk.company_id == company_id
        )
        result = await self.db.exec(statement)
        chunks = list(result.all())

        if not chunks:
            return []

        # BM25 search over chunk content
        memories = [c.content for c in chunks]
        bm25_results = bm25_search(query, memories, top_k=top_k)

        # Build results with hybrid scoring
        results: list[dict] = []
        for idx, bm25_score_val in bm25_results:
            chunk = chunks[idx]
            # Vector similarity stub - placeholder cosine similarity score
            vector_score = self._compute_vector_similarity_stub(query, chunk.content)
            # Combined score: weighted average (BM25 dominant, vector as supplement)
            combined_score = 0.7 * bm25_score_val + 0.3 * vector_score

            results.append({
                "chunk": chunk,
                "bm25_score": bm25_score_val,
                "vector_score": vector_score,
                "combined_score": combined_score,
            })

        # Sort by combined score
        results.sort(key=lambda x: x["combined_score"], reverse=True)
        return results[:top_k]

    def _compute_vector_similarity_stub(self, query: str, content: str) -> float:
        """Stub for vector similarity computation.

        Returns a placeholder cosine similarity score based on token overlap.
        In production, this would use actual embedding vectors.

        Args:
            query: The search query.
            content: The chunk content.

        Returns:
            A placeholder similarity score between 0.0 and 1.0.
        """
        query_tokens = set(tokenize(query))
        content_tokens = set(tokenize(content))

        if not query_tokens or not content_tokens:
            return 0.0

        # Jaccard-like overlap as a proxy for cosine similarity
        intersection = query_tokens & content_tokens
        union = query_tokens | content_tokens
        return len(intersection) / len(union) if union else 0.0

    def rerank(
        self,
        query: str,
        results: list[dict],
        top_k: int = 3,
    ) -> list[dict]:
        """Rerank search results based on relevance heuristics.

        Applies multiple heuristic signals to rerank results:
        - Term overlap: How many query terms appear in the chunk
        - Position: Earlier chunks (lower chunk_index) are slightly preferred
        - Freshness: More recently created chunks get a small boost

        Args:
            query: The original search query.
            results: List of result dicts from the search method.
            top_k: Number of top results to return after reranking.

        Returns:
            Reranked list of result dicts, limited to top_k.
        """
        if not results:
            return []

        query_tokens = set(tokenize(query))

        scored_results: list[tuple[float, dict]] = []
        for result in results:
            chunk = result.get("chunk")
            combined_score = result.get("combined_score", 0.0)

            # Term overlap signal
            if chunk is not None:
                chunk_content = chunk.content if hasattr(chunk, "content") else str(chunk)
                chunk_tokens = set(tokenize(chunk_content))
                overlap_ratio = (
                    len(query_tokens & chunk_tokens) / len(query_tokens)
                    if query_tokens
                    else 0.0
                )
            else:
                overlap_ratio = 0.0

            # Position signal: prefer earlier chunks (lower index)
            chunk_index = 0
            if chunk is not None and hasattr(chunk, "chunk_index"):
                chunk_index = chunk.chunk_index
            position_boost = 1.0 / (1.0 + chunk_index * 0.1)

            # Freshness signal: more recent chunks get a small boost
            freshness_boost = 1.0
            if chunk is not None and hasattr(chunk, "created_at") and chunk.created_at:
                # Normalize: newer is better (simple linear decay)
                age_hours = (
                    datetime.now(timezone.utc) - chunk.created_at
                ).total_seconds() / 3600.0
                freshness_boost = 1.0 / (1.0 + age_hours * 0.001)

            # Weighted reranking score
            rerank_score = (
                0.5 * combined_score
                + 0.3 * overlap_ratio
                + 0.1 * position_boost
                + 0.1 * freshness_boost
            )

            scored_results.append((rerank_score, result))

        # Sort by rerank score descending
        scored_results.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored_results[:top_k]]

    def assemble_context(
        self,
        results: list[dict],
        max_tokens: int = 4000,
    ) -> str:
        """Assemble a context window from retrieved chunks within a token budget.

        Builds a formatted context string from search results, estimating
        token usage at 4 characters per token. Stops adding chunks when the
        budget would be exceeded.

        Args:
            results: List of result dicts (from search or rerank).
            max_tokens: Maximum token budget for the assembled context.

        Returns:
            Formatted context string ready for inclusion in agent prompts.
        """
        max_chars = max_tokens * 4  # Estimate: 4 characters per token
        context_parts: list[str] = []
        current_chars = 0

        for i, result in enumerate(results):
            chunk = result.get("chunk")
            if chunk is None:
                continue

            chunk_content = chunk.content if hasattr(chunk, "content") else str(chunk)

            # Format the chunk with a separator
            formatted = f"[Source {i + 1}]\n{chunk_content}\n"
            chunk_chars = len(formatted)

            # Check if adding this chunk would exceed the budget
            if current_chars + chunk_chars > max_chars:
                # Try to fit a truncated version
                remaining = max_chars - current_chars
                if remaining > 50:  # Only add if we can fit meaningful content
                    truncated = formatted[:remaining - 3] + "..."
                    context_parts.append(truncated)
                break

            context_parts.append(formatted)
            current_chars += chunk_chars

        return "\n".join(context_parts)
