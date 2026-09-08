"""Vault indexing engine (ADR 0002 §13, §21, Phase 1B-3A).

Turns registered notes into retrievable chunks. The scanner decides *which* notes
need work by maintaining ``index_status``; this module does the work for the ones
marked stale, then records the outcome.

Reuses the existing RAG path rather than building a parallel one:
``MarkdownParser`` splits the body, ``RAGPipeline.chunk_document`` and
``index_chunks`` produce and store ``knowledge_chunks`` rows under
``source_type='obsidian_document'``. Nothing here re-implements chunking,
embedding, or retrieval.

Still read-only with respect to the vault: notes are read through the provider
and never written.

Outcomes recorded on the document row:

``indexed``
    Chunks stored with embedding vectors, or with no provider configured at all
    (keyword-only retrieval is a deliberate, visible configuration).
``partial``
    Chunks stored but their vectors were not. ``RAGPipeline.index_chunks`` drops
    vectors of the wrong width rather than failing the insert, which would
    otherwise leave retrieval silently degraded to keyword-only with nothing to
    show for it (ADR 0002 §21). This state is that missing signal.
``failed``
    The note could not be read, or indexing raised. The row keeps its previous
    chunks rather than being left with none.

A ``failed`` document is retried on later passes, bounded by
``MAX_INDEX_ATTEMPTS``, but only when the failure looked transient — a provider
outage, a timeout, a rate limit, a momentary database problem. A failure that
will recur identically no matter how often it is retried (a security rejection, a
deterministic parse error, an unreadable file) is charged the whole attempt budget
at once, so it drops out of the work queue immediately instead of burning two more
passes to reach the same answer. Either way an operator sees ``failed`` with
``last_error``; the difference is only how much effort is spent re-proving it.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.knowledge.embeddings import get_embedding_provider
from nexus.knowledge.parsers import MarkdownParser
from nexus.knowledge.rag import RAGPipeline
from nexus.models.knowledge import SOURCE_TYPE_OBSIDIAN_DOCUMENT
from nexus.models.obsidian import (
    INDEX_STATUS_FAILED,
    INDEX_STATUS_INDEXED,
    INDEX_STATUS_PARTIAL,
    INDEX_STATUS_STALE,
    MAX_INDEX_ATTEMPTS,
    ObsidianDocument,
)
from nexus.obsidian.provider import ObsidianReader
from nexus.obsidian.security import VaultSecurityError, safe_reason
from nexus.obsidian.wikilinks import note_links

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    """What one indexing pass did.

    Attributes:
        indexed: Vault paths chunked and embedded successfully.
        partial: Vault paths chunked but stored without vectors.
        failed: Vault paths that could not be indexed, with the reason.
        skipped: Vault paths with no indexable content (an empty note).
        chunks_written: Total chunk rows created across all documents.
    """

    indexed: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    chunks_written: int = 0

    def counts(self) -> dict[str, int]:
        """A flat summary suitable for logging or an API response."""
        return {
            "indexed": len(self.indexed),
            "partial": len(self.partial),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "chunks_written": self.chunks_written,
        }


class VaultIndexer:
    """Chunks and embeds one company's registered vault notes.

    Example:
        >>> indexer = VaultIndexer(db, company_id)
        >>> result = await indexer.index_stale()
        >>> result.counts()["indexed"]
        4
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: uuid.UUID,
        reader: ObsidianReader | None = None,
        pipeline: RAGPipeline | None = None,
    ) -> None:
        """Bind an indexer to a company's vault and database session.

        Args:
            db: Async session. The indexer flushes through the pipeline but never
                commits — the caller owns the transaction, so a failure cannot
                leave a document marked ``indexed`` with no chunks behind it.
            company_id: The company whose documents are indexed. The reader
                derives the vault root from it, so an indexer cannot reach
                another tenant's notes.
            reader: Optional reader override, for tests.
            pipeline: Optional pipeline override. By default one is built with
                ``MarkdownParser`` and the configured embedding provider.
        """
        self._db = db
        self._company_id = company_id
        self._reader = reader or ObsidianReader(company_id)
        self._pipeline = pipeline or RAGPipeline(
            db=db,
            embedding_provider=get_embedding_provider(),
            parser=MarkdownParser(),
        )

    async def index_stale(self, limit: int | None = None) -> IndexResult:
        """Index every document with pending work.

        Pending means marked ``stale`` by the scanner, or previously ``failed``
        with retry attempts left. A document that has spent its
        ``MAX_INDEX_ATTEMPTS`` budget is left alone until its content changes,
        which is what keeps a permanent failure from looping.

        Args:
            limit: Optional cap on documents processed in one pass, so a large
                first index can be run in batches without holding one
                transaction open across the whole vault.

        Returns:
            An :class:`IndexResult` describing each document's outcome.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
        """
        rows = await self._stale_documents(limit)
        result = IndexResult()
        for row in rows:
            await self._index_document(row, result)
        await self._db.flush()
        logger.info(
            "Obsidian vault index for company %s: %s", self._company_id, result.counts()
        )
        return result

    async def index_document(self, nexus_id: uuid.UUID) -> IndexResult:
        """Index one document by id, whatever its current status.

        Used to force a reindex of a single note.

        Args:
            nexus_id: The document to index.

        Returns:
            An :class:`IndexResult` covering just that document. A document that
            does not belong to this company yields an empty result rather than an
            error: it does not exist as far as this caller is concerned.
        """
        statement = select(ObsidianDocument).where(
            ObsidianDocument.company_id == self._company_id,
            ObsidianDocument.nexus_id == nexus_id,
        )
        row = (await self._db.execute(statement)).scalars().one_or_none()
        result = IndexResult()
        if row is None:
            return result
        await self._index_document(row, result)
        await self._db.flush()
        return result

    async def record_failure(
        self, nexus_id: uuid.UUID, exc: BaseException, *, retryable: bool | None = None
    ) -> bool:
        """Record a failed attempt against one document, without indexing it.

        Exists for the Temporal activity, which catches an exception that escaped
        :meth:`index_document` and needs the failure written on a *fresh* session
        after the original was rolled back. Routing it here rather than issuing an
        UPDATE keeps ``attempt_count`` accounting in one place, so the bounded
        retry from Phase 1B-3C still governs whether a later pass tries again.

        Args:
            nexus_id: The document that failed.
            exc: The exception, used for the client-safe reason.
            retryable: Override the classification; by default it is derived the
                same way as for an in-pass failure.

        Returns:
            True if a row was found and marked, False if the document is gone.
        """
        statement = select(ObsidianDocument).where(
            ObsidianDocument.company_id == self._company_id,
            ObsidianDocument.nexus_id == nexus_id,
        )
        row = (await self._db.execute(statement)).scalars().one_or_none()
        if row is None:
            return False
        decided = _is_retryable(exc) if retryable is None else retryable
        self._fail(row, IndexResult(), exc, retryable=decided)
        await self._db.flush()
        return True

    async def pending_document_ids(self, limit: int | None = None) -> list[uuid.UUID]:
        """Ids of the documents with pending indexing work, in pass order.

        Exists for the Temporal workflow, which needs to know *what* to index
        before it starts indexing so each document becomes its own activity. It
        shares :meth:`_stale_documents` with :meth:`index_stale`, so the durable
        path and the synchronous path can never disagree about what is pending.

        Args:
            limit: Optional cap, same meaning as in :meth:`index_stale`.

        Returns:
            Document ids, ordered stale-first then by vault path.
        """
        rows = await self._stale_documents(limit)
        return [row.nexus_id for row in rows]

    async def _stale_documents(self, limit: int | None) -> list[ObsidianDocument]:
        """Load this company's pending documents in a stable order.

        Pending means never indexed (``stale``), or previously ``failed`` with
        attempts left. A ``failed`` row at ``MAX_INDEX_ATTEMPTS`` is excluded,
        which is what bounds retrying; ``partial`` is excluded because its text is
        already searchable and re-running the same wrong-width provider would
        produce the same result.

        Stale rows sort first, so a fresh edit is never starved behind a queue of
        failures working through their retry budget.
        """
        statement = (
            select(ObsidianDocument)
            .where(
                ObsidianDocument.company_id == self._company_id,
                or_(
                    ObsidianDocument.index_status == INDEX_STATUS_STALE,
                    and_(
                        ObsidianDocument.index_status == INDEX_STATUS_FAILED,
                        ObsidianDocument.attempt_count < MAX_INDEX_ATTEMPTS,
                    ),
                ),
            )
            .order_by(
                ObsidianDocument.index_status != INDEX_STATUS_STALE,
                ObsidianDocument.vault_path,
            )
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list((await self._db.execute(statement)).scalars().all())

    async def _index_document(self, row: ObsidianDocument, result: IndexResult) -> None:
        """Chunk, embed and store one document, recording its outcome."""
        try:
            note = self._reader.read_note(row.vault_path)
        except (VaultSecurityError, OSError) as exc:
            # A note deleted or made unreadable between scan and index. Leave the
            # existing chunks in place: the scanner owns removal, and dropping
            # them here would make the failure look like a successful empty index.
            # Not retryable: the file is gone, outside the vault boundary, or
            # oversized. Re-reading it will fail identically, so charge the whole
            # budget rather than spending two more passes proving it.
            self._fail(row, result, exc, retryable=False)
            return

        # Relationships come from the note itself (ADR 0002 §14), so they are
        # recorded here rather than on any outcome branch below: a note whose
        # body is empty of prose can still be a hub of links, and one whose
        # indexing fails has not stopped relating to its neighbours.
        #
        # Best-effort, because retrieval outranks link discovery: a note that
        # cannot be parsed for links is still worth searching, so an extraction
        # failure costs this note its edges rather than its index.
        try:
            row.wikilink_targets = note_links(note.parsed.metadata, note.parsed.body) or None
        except Exception:  # noqa: BLE001 - a bad link must not fail indexing
            logger.exception(
                "Wikilink extraction failed for %s (company %s); indexing the note anyway",
                row.vault_path,
                self._company_id,
            )
            row.wikilink_targets = None

        # The body only. Frontmatter is metadata: indexing it would put YAML keys
        # into retrieval results and let a tag match outrank the prose.
        chunks = [
            text
            for text in map(_chunk_text, self._pipeline.parse_document(note.parsed.body))
            if text
        ]

        if not chunks:
            # An empty or frontmatter-only note. Drop any stale chunks so it stops
            # answering searches, and treat it as indexed: there is nothing to index
            # and nothing wrong.
            await self._pipeline.delete_page_chunks(
                self._company_id, row.nexus_id, SOURCE_TYPE_OBSIDIAN_DOCUMENT
            )
            self._mark(row, INDEX_STATUS_INDEXED, note_hash=note.content_hash)
            result.skipped.append(row.vault_path)
            return

        try:
            # A savepoint, because reindex_page deletes the old chunks before it
            # inserts the new ones. Without one, a failure between those two
            # steps leaves the DELETE pending in the session, the pass continues,
            # and the caller's commit destroys a document's working index while
            # recording status='failed' — a searchable note silently becomes
            # unsearchable. Rolling back to the savepoint undoes only this
            # document's delete-and-insert, leaving earlier documents in the pass
            # intact.
            async with self._db.begin_nested():
                records = await self._pipeline.reindex_page(
                    self._company_id,
                    row.nexus_id,
                    chunks,
                    SOURCE_TYPE_OBSIDIAN_DOCUMENT,
                )
        except Exception as exc:  # noqa: BLE001 - one bad note must not stop the pass
            logger.exception(
                "Indexing failed for %s (company %s)", row.vault_path, self._company_id
            )
            self._fail(row, result, exc, retryable=_is_retryable(exc))
            return

        result.chunks_written += len(records)
        provider = self._pipeline.embedding_provider
        vectors_expected = provider is not None and provider.dimension > 0
        vectors_stored = any(record.embedding_vector is not None for record in records)

        if vectors_expected and not vectors_stored:
            # index_chunks dropped the vectors — wrong width for the column. The
            # chunks are searchable by keyword, so this is degradation, not
            # failure, and it must be visible rather than silent.
            self._mark(
                row,
                INDEX_STATUS_PARTIAL,
                note_hash=note.content_hash,
                provider=provider,
            )
            result.partial.append(row.vault_path)
            return

        self._mark(
            row,
            INDEX_STATUS_INDEXED,
            note_hash=note.content_hash,
            provider=provider,
        )
        result.indexed.append(row.vault_path)

    def _fail(
        self,
        row: ObsidianDocument,
        result: IndexResult,
        exc: BaseException,
        *,
        retryable: bool,
    ) -> None:
        """Record a failed attempt and decide whether it will be retried.

        A retryable failure spends one attempt. A non-retryable one spends the
        whole budget, so the document drops out of the next pass immediately —
        expressed as an attempt count rather than a separate status, because the
        operator-facing fact is the same either way: it failed, here is why.
        """
        reason = safe_reason(exc)
        spent = 1 if retryable else MAX_INDEX_ATTEMPTS
        row.attempt_count = min(row.attempt_count + spent, MAX_INDEX_ATTEMPTS)
        row.last_error = reason[:500]
        self._mark(row, INDEX_STATUS_FAILED, reset_attempts=False)
        result.failed.append((row.vault_path, reason))

    def _mark(
        self,
        row: ObsidianDocument,
        status: str,
        note_hash: str | None = None,
        provider: object | None = None,
        reset_attempts: bool = True,
    ) -> None:
        """Record an indexing outcome on the document row.

        ``content_hash`` is refreshed from the note actually indexed, so a note
        edited between scan and index does not leave the row claiming to describe
        content that was never chunked. The model and dimension are recorded per
        document so a later provider change is detectable on read (ADR 0002 §21).

        ``indexed_at`` advances only on an outcome that produced an index, so it
        keeps meaning "when this document last became searchable" rather than
        "when we last touched it" — ``last_attempt_at`` is the field for that.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        row.index_status = status
        row.last_attempt_at = now
        row.updated_at = now
        if status != INDEX_STATUS_FAILED:
            row.indexed_at = now
        if reset_attempts:
            # Consecutive failures only: a document that fails once and then
            # indexes must not carry that failure into its next edit.
            row.attempt_count = 0
            row.last_error = None
        if note_hash is not None:
            row.content_hash = note_hash
        if provider is not None:
            row.embedding_model = _provider_model(provider)
            dimension = getattr(provider, "dimension", 0)
            row.embedding_dimension = dimension or None
        self._db.add(row)


def _is_retryable(exc: BaseException) -> bool:
    """Whether a failure is worth another pass.

    Retryable means "the same input might succeed later": a provider outage, a
    timeout, a rate limit, a momentary database problem. Non-retryable means the
    failure is a property of the input or the configuration, so a retry re-proves
    the same answer — a security rejection, a deterministic parse or validation
    error, a value the schema will not accept.

    Unknown exception types default to retryable. The cost of being wrong that way
    is two wasted passes, bounded by ``MAX_INDEX_ATTEMPTS``; the cost of the other
    default is a transient blip permanently parking a document at ``failed``.

    Args:
        exc: The exception raised while indexing one document.

    Returns:
        True if the document should be picked up by a later pass.
    """
    # A path or policy rejection is deterministic by construction.
    if isinstance(exc, VaultSecurityError):
        return False
    # Bad data or a bad argument reaching the pipeline: the same note produces the
    # same error next time. ValueError also covers RAGPipeline's rejection of an
    # unsupported chunking strategy.
    if isinstance(exc, (TypeError, ValueError, KeyError, AttributeError)):
        return False
    # DBAPI integrity violations are the data's fault, not the connection's.
    if isinstance(exc, IntegrityError):
        return False
    # Everything else — provider outages, timeouts, rate limits, OperationalError,
    # connection resets — gets another attempt.
    return True


def _chunk_text(chunk: object) -> str:
    """Text of one parsed chunk, stripped, or empty if it carries none.

    ``parse_document`` returns ``ParsedChunk`` objects when a parser is set and
    plain strings when it falls back to ``chunk_document``, so accept both rather
    than depending on which branch a caller's pipeline took.
    """
    content = chunk if isinstance(chunk, str) else getattr(chunk, "content", "")
    return content.strip() if isinstance(content, str) else ""


def _provider_model(provider: object) -> str | None:
    """Best-effort model name for an embedding provider.

    Providers do not share a model attribute — the OpenAI and Ollama ones keep a
    private ``_model``, the local stub has none — so fall back to the class name,
    which is still enough to tell that the provider changed.
    """
    model = getattr(provider, "_model", None)
    if isinstance(model, str) and model:
        return model[:100]
    return type(provider).__name__[:100]
