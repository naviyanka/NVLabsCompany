"""Knowledge Graph - file-backed knowledge store with BM25 search.

Provides document ingestion (file or text), paragraph-based chunking,
BM25-powered search, and full CRUD operations over a local directory store.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from nexus.knowledge.graph_types import IngestResult, KgHit, KgMeta, KnowledgeStatus
from nexus.memory.retriever import search as bm25_search


class KnowledgeManager:
    """File-backed knowledge store with ingest, search, and CRUD operations.

    Directory layout::

        <root>/
            index.json          - JSON array of KgMeta entries
            chunks/
                <doc_id>/
                    0.txt       - First chunk
                    1.txt       - Second chunk
                    ...

    Attributes:
        root: Filesystem path to the knowledge store directory.
    """

    def __init__(self, root: str) -> None:
        """Initialize the KnowledgeManager with a storage root directory.

        Creates the root directory and chunks subdirectory if they do not exist.

        Args:
            root: Filesystem path for the knowledge store.
        """
        self.root = root
        self._root_path = Path(root)
        self._index_path = self._root_path / "index.json"
        self._chunks_path = self._root_path / "chunks"
        self._root_path.mkdir(parents=True, exist_ok=True)
        self._chunks_path.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> list[dict]:
        """Load the index.json file, returning an empty list if missing.

        Returns:
            List of raw metadata dicts from the index file.
        """
        if not self._index_path.exists():
            return []
        with open(self._index_path, encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, entries: list[dict]) -> None:
        """Persist the metadata index to index.json.

        Args:
            entries: List of metadata dicts to write.
        """
        with open(self._index_path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)

    def _chunk_content(self, content: str, chunk_size: int = 500) -> list[str]:
        """Split content into paragraph-based chunks respecting a size limit.

        Splits on double-newlines first (paragraph boundaries). If a paragraph
        exceeds chunk_size, it is further split at chunk_size boundaries.
        Small consecutive paragraphs are merged until they reach chunk_size.

        Args:
            content: The full text to chunk.
            chunk_size: Target maximum characters per chunk.

        Returns:
            List of non-empty chunk strings.
        """
        paragraphs = re.split(r"\n\n+", content)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if not paragraphs:
            # If no paragraph structure, fall back to fixed-size splitting
            if content.strip():
                return [content.strip()]
            return []

        chunks: list[str] = []
        current_chunk: list[str] = []
        current_size = 0

        for para in paragraphs:
            para_len = len(para)

            # If a single paragraph exceeds chunk_size, split it by itself
            if para_len > chunk_size:
                # Flush anything accumulated
                if current_chunk:
                    chunks.append("\n\n".join(current_chunk))
                    current_chunk = []
                    current_size = 0
                # Split the large paragraph into fixed-size pieces
                start = 0
                while start < para_len:
                    end = start + chunk_size
                    piece = para[start:end].strip()
                    if piece:
                        chunks.append(piece)
                    start = end
            elif current_size + para_len + 2 > chunk_size and current_chunk:
                # Flush current chunk and start a new one
                chunks.append("\n\n".join(current_chunk))
                current_chunk = [para]
                current_size = para_len
            else:
                current_chunk.append(para)
                current_size += para_len + (2 if current_chunk else 0)

        # Flush remaining
        if current_chunk:
            chunks.append("\n\n".join(current_chunk))

        return chunks

    def _ingest_content(
        self,
        content: str,
        title: str,
        source: str,
        tags: list[str] | None = None,
        mime: str | None = None,
        modality: str = "text",
        caption: str | None = None,
        chunk_size: int = 500,
    ) -> IngestResult:
        """Core ingestion logic: chunk, persist, and index a document.

        Args:
            content: The full text content to ingest.
            title: Human-readable title.
            source: Origin path or descriptor.
            tags: Classification tags.
            mime: MIME type of the original source.
            modality: Content modality (e.g. 'text', 'code', 'image').
            caption: Optional short description.
            chunk_size: Target chunk size in characters.

        Returns:
            IngestResult with the assigned doc_id, chunk_count, and metadata.
        """
        doc_id = uuid.uuid4().hex
        chunks = self._chunk_content(content, chunk_size)
        chunk_count = len(chunks)

        # Write chunks to disk
        doc_chunks_dir = self._chunks_path / doc_id
        doc_chunks_dir.mkdir(parents=True, exist_ok=True)
        for idx, chunk_text in enumerate(chunks):
            chunk_file = doc_chunks_dir / f"{idx}.txt"
            chunk_file.write_text(chunk_text, encoding="utf-8")

        # Build metadata
        meta_dict = {
            "id": doc_id,
            "title": title,
            "source": source,
            "modality": modality,
            "mime": mime,
            "bytes": len(content.encode("utf-8")),
            "tags": tags or [],
            "caption": caption,
            "chunk_count": chunk_count,
            "added_at": datetime.now(UTC).isoformat(),
        }

        # Update index
        index = self._load_index()
        index.append(meta_dict)
        self._save_index(index)

        meta = KgMeta.model_validate(meta_dict)
        return IngestResult(doc_id=doc_id, chunk_count=chunk_count, meta=meta)

    def ingest_file(
        self,
        src_path: str,
        title: str | None = None,
        tags: list[str] | None = None,
        caption: str | None = None,
    ) -> IngestResult:
        """Ingest a file from disk into the knowledge store.

        Reads the file content, determines MIME type from extension,
        and delegates to _ingest_content.

        Args:
            src_path: Filesystem path to the file to ingest.
            title: Title override; defaults to the filename.
            tags: Classification tags.
            caption: Optional short description.

        Returns:
            IngestResult with metadata about the ingested document.

        Raises:
            FileNotFoundError: If src_path does not exist.
        """
        path = Path(src_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {src_path}")

        content = path.read_text(encoding="utf-8")
        resolved_title = title if title else path.name
        mime_type, _ = mimetypes.guess_type(str(path))

        return self._ingest_content(
            content=content,
            title=resolved_title,
            source=str(path),
            tags=tags,
            mime=mime_type,
            modality="text",
            caption=caption,
        )

    def ingest_text(
        self,
        text: str,
        title: str | None = None,
        tags: list[str] | None = None,
    ) -> IngestResult:
        """Ingest inline text content into the knowledge store.

        Args:
            text: The text content to ingest.
            title: Title for the document; defaults to 'Untitled'.
            tags: Classification tags.

        Returns:
            IngestResult with metadata about the ingested document.
        """
        resolved_title = title if title else "Untitled"
        return self._ingest_content(
            content=text,
            title=resolved_title,
            source="inline",
            tags=tags,
            mime=None,
            modality="text",
        )

    def search(self, query: str, limit: int = 10) -> list[KgHit]:
        """Search the knowledge store using BM25 ranking.

        Loads all chunks, scores them against the query using BM25,
        and returns the top results as KgHit objects.

        Args:
            query: The search query string.
            limit: Maximum number of results to return.

        Returns:
            List of KgHit objects sorted by relevance (highest first).
        """
        index = self._load_index()
        if not index:
            return []

        # Build corpus: list of (doc_meta, chunk_idx, chunk_text)
        corpus: list[tuple[dict, int, str]] = []
        for meta_dict in index:
            doc_id = meta_dict["id"]
            doc_chunks_dir = self._chunks_path / doc_id
            if not doc_chunks_dir.exists():
                continue
            chunk_count = meta_dict.get("chunk_count", 0)
            for idx in range(chunk_count):
                chunk_file = doc_chunks_dir / f"{idx}.txt"
                if chunk_file.exists():
                    text = chunk_file.read_text(encoding="utf-8")
                    corpus.append((meta_dict, idx, text))

        if not corpus:
            return []

        # Use BM25 search from retriever
        memories = [item[2] for item in corpus]
        results = bm25_search(query, memories, top_k=limit)

        hits: list[KgHit] = []
        for corpus_idx, score in results:
            meta_dict, chunk_idx, snippet = corpus[corpus_idx]
            hits.append(
                KgHit(
                    doc_id=meta_dict["id"],
                    title=meta_dict["title"],
                    source=meta_dict["source"],
                    chunk_idx=chunk_idx,
                    score=score,
                    snippet=snippet,
                )
            )

        return hits

    def list_docs(self) -> list[KgMeta]:
        """List all documents in the knowledge store.

        Returns:
            List of KgMeta objects for every ingested document.
        """
        index = self._load_index()
        return [KgMeta.model_validate(entry) for entry in index]

    def get_doc(self, doc_id: str) -> dict | None:
        """Retrieve a document's metadata and full text by ID.

        Reconstructs the full text by reading and joining all chunk files.

        Args:
            doc_id: The document identifier.

        Returns:
            Dict with 'meta' (KgMeta) and 'text' (str) keys, or None if not found.
        """
        index = self._load_index()
        meta_dict = next((e for e in index if e["id"] == doc_id), None)
        if meta_dict is None:
            return None

        # Reconstruct full text from chunks
        doc_chunks_dir = self._chunks_path / doc_id
        chunk_count = meta_dict.get("chunk_count", 0)
        text_parts: list[str] = []
        for idx in range(chunk_count):
            chunk_file = doc_chunks_dir / f"{idx}.txt"
            if chunk_file.exists():
                text_parts.append(chunk_file.read_text(encoding="utf-8"))

        meta = KgMeta.model_validate(meta_dict)
        return {"meta": meta, "text": "\n\n".join(text_parts)}

    def remove_doc(self, doc_id: str) -> bool:
        """Remove a document from the knowledge store.

        Deletes the document from the index and removes its chunk directory.

        Args:
            doc_id: The document identifier to remove.

        Returns:
            True if the document was found and removed, False otherwise.
        """
        index = self._load_index()
        original_len = len(index)
        index = [e for e in index if e["id"] != doc_id]

        if len(index) == original_len:
            return False

        self._save_index(index)

        # Remove chunk directory
        doc_chunks_dir = self._chunks_path / doc_id
        if doc_chunks_dir.exists():
            shutil.rmtree(doc_chunks_dir)

        return True

    def stats(self) -> KnowledgeStatus:
        """Compute status summary of the knowledge store.

        Returns:
            KnowledgeStatus with document count, chunk count, and modality breakdown.
        """
        index = self._load_index()
        doc_count = len(index)
        chunk_count = sum(e.get("chunk_count", 0) for e in index)

        by_modality: dict[str, int] = {}
        for entry in index:
            modality = entry.get("modality", "text")
            by_modality[modality] = by_modality.get(modality, 0) + 1

        return KnowledgeStatus(
            enabled=True,
            root=self.root,
            doc_count=doc_count,
            chunk_count=chunk_count,
            by_modality=by_modality,
        )
