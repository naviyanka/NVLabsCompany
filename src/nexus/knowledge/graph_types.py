"""Knowledge Graph types - Pydantic models for the file-backed knowledge store."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KgMeta(BaseModel):
    """Metadata for a single ingested document in the knowledge store.

    Attributes:
        id: Unique document identifier (uuid4 hex).
        title: Human-readable document title.
        source: Origin path or descriptor for the document.
        modality: Content modality (default 'text').
        mime: MIME type of the original file, or None.
        bytes_: Size in bytes of the original content (serialized as 'bytes').
        tags: User-supplied classification tags.
        caption: Optional short description or caption.
        chunk_count: Number of chunks the document was split into.
        added_at: ISO 8601 timestamp when the document was ingested.
    """

    id: str
    title: str
    source: str
    modality: str = "text"
    mime: str | None = None
    bytes_: int = Field(alias="bytes")
    tags: list[str] = Field(default_factory=list)
    caption: str | None = None
    chunk_count: int = 0
    added_at: str = ""

    model_config = {"populate_by_name": True}


class KgHit(BaseModel):
    """A single search result from the knowledge store.

    Attributes:
        doc_id: The document this chunk belongs to.
        title: Title of the parent document.
        source: Source of the parent document.
        chunk_idx: Zero-based index of the matching chunk.
        score: BM25 relevance score.
        snippet: The chunk text content.
    """

    doc_id: str
    title: str
    source: str
    chunk_idx: int
    score: float
    snippet: str


class IngestResult(BaseModel):
    """Result returned after successfully ingesting a document.

    Attributes:
        doc_id: The newly assigned document identifier.
        chunk_count: Number of chunks created.
        meta: Full metadata record for the ingested document.
    """

    doc_id: str
    chunk_count: int
    meta: KgMeta


class KnowledgeStatus(BaseModel):
    """Overall status summary of the knowledge store.

    Attributes:
        enabled: Whether the knowledge store is active.
        root: Filesystem path to the store root directory.
        doc_count: Total number of ingested documents.
        chunk_count: Total number of chunks across all documents.
        by_modality: Document counts grouped by modality.
    """

    enabled: bool
    root: str
    doc_count: int
    chunk_count: int
    by_modality: dict[str, int] = Field(default_factory=dict)
