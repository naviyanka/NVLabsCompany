"""Temporal activities for Obsidian vault indexing (ADR 0002 §23, Phase 1C).

Two activities, one per unit of durable work:

``list_pending_obsidian_documents_activity``
    Reads which documents need indexing. Cheap, retry-safe, no side effects.
``index_obsidian_document_activity``
    Chunks and embeds exactly ONE document. Embedding is a billed network call,
    so the workflow runs this with ``ONCE_ONLY`` — a Temporal retry would be a
    second charge for the same document.

One document per activity rather than one activity for the whole vault, because
that is what makes the work restartable: a worker that dies mid-pass loses one
document's attempt, and the workflow history already records which documents
completed. It also means no activity runs long enough to need heartbeating.

**Transaction ownership.** Under Temporal there is no request-scoped session, so
each activity opens its own and commits it. That is a real difference from the
synchronous path, where the route owns the transaction and the scanner/indexer
only flush: an activity that did not commit would do its work and throw it away.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from nexus.temporal._sdk import activity_defn

logger = logging.getLogger(__name__)

# Outcomes reported back to the workflow. These mirror IndexResult's buckets, but
# per document rather than per pass.
OUTCOME_INDEXED = "indexed"
OUTCOME_PARTIAL = "partial"
OUTCOME_SKIPPED = "skipped"
OUTCOME_FAILED = "failed"
OUTCOME_VANISHED = "vanished"


@dataclass
class PendingDocumentsInput:
    """Which company's pending documents to list, and how many."""

    company_id: str
    limit: int | None = None


@dataclass
class PendingDocumentsOutput:
    """Document ids awaiting indexing, in the order a pass would take them.

    Ids are strings rather than UUIDs: they cross the workflow/activity boundary
    as JSON, and a UUID does not round-trip through it.
    """

    nexus_ids: list[str] = field(default_factory=list)


@dataclass
class IndexDocumentInput:
    """One document to index, scoped to its company."""

    company_id: str
    nexus_id: str


@dataclass
class IndexDocumentOutput:
    """What happened to one document.

    ``reason`` carries a client-safe description only (see
    ``obsidian.security.safe_reason``) — no absolute host paths.
    """

    nexus_id: str
    outcome: str
    vault_path: str = ""
    chunks_written: int = 0
    reason: str = ""


@activity_defn
async def list_pending_obsidian_documents_activity(
    input: PendingDocumentsInput,
) -> PendingDocumentsOutput:
    """List the documents with pending indexing work for one company.

    Pending means the scanner marked them stale, or a previous attempt failed and
    retry budget remains. The selection itself lives in ``VaultIndexer`` so this
    cannot drift from what the synchronous path would pick.
    """
    from nexus.database import async_session_factory
    from nexus.obsidian.indexer import VaultIndexer

    company_id = uuid.UUID(input.company_id)
    async with async_session_factory() as db:
        indexer = VaultIndexer(db, company_id)
        ids = await indexer.pending_document_ids(limit=input.limit)
    return PendingDocumentsOutput(nexus_ids=[str(i) for i in ids])


@activity_defn
async def index_obsidian_document_activity(
    input: IndexDocumentInput,
) -> IndexDocumentOutput:
    """Chunk and embed one document, committing the result.

    Returns an outcome rather than raising, for every failure the indexer already
    classifies. A raise would make Temporal mark the activity failed and — under
    the ``ONCE_ONLY`` policy the workflow uses — abandon the document without the
    application's own retry accounting being written. Recording the outcome keeps
    ``attempt_count`` authoritative, so the bounded retry from Phase 1B-3C still
    governs whether a later pass tries again.
    """
    from nexus.database import async_session_factory
    from nexus.obsidian.indexer import VaultIndexer
    from nexus.obsidian.security import safe_reason

    company_id = uuid.UUID(input.company_id)
    nexus_id = uuid.UUID(input.nexus_id)

    async with async_session_factory() as db:
        indexer = VaultIndexer(db, company_id)
        try:
            result = await indexer.index_document(nexus_id)
            await db.commit()
        except Exception as exc:
            await db.rollback()
            if _is_workflow_fatal(exc):
                # Every remaining document would hit this too, so isolating it
                # would burn each one's retry budget to re-prove the same thing.
                logger.exception(
                    "Obsidian indexing hit a workflow-fatal condition on document "
                    "%s (company %s); failing the run",
                    nexus_id,
                    company_id,
                )
                raise

            # Document-scoped: record it and let the batch continue. The rollback
            # above already discarded this document's partial work, so a previously
            # successful index is untouched — the failure-preservation invariant.
            logger.exception(
                "Obsidian indexing failed for document %s (company %s); "
                "continuing with the rest of the run",
                nexus_id,
                company_id,
            )
            await _record_isolated_failure(company_id, nexus_id, exc)
            return IndexDocumentOutput(
                nexus_id=input.nexus_id,
                outcome=OUTCOME_FAILED,
                reason=safe_reason(exc),
            )

    counts = result.counts()
    if result.indexed:
        return IndexDocumentOutput(
            nexus_id=input.nexus_id,
            outcome=OUTCOME_INDEXED,
            vault_path=result.indexed[0],
            chunks_written=counts["chunks_written"],
        )
    if result.partial:
        return IndexDocumentOutput(
            nexus_id=input.nexus_id,
            outcome=OUTCOME_PARTIAL,
            vault_path=result.partial[0],
            chunks_written=counts["chunks_written"],
            reason="Chunks stored without embedding vectors; keyword search only.",
        )
    if result.skipped:
        return IndexDocumentOutput(
            nexus_id=input.nexus_id,
            outcome=OUTCOME_SKIPPED,
            vault_path=result.skipped[0],
            reason="No indexable content.",
        )
    if result.failed:
        path, reason = result.failed[0]
        return IndexDocumentOutput(
            nexus_id=input.nexus_id,
            outcome=OUTCOME_FAILED,
            vault_path=path,
            reason=reason,
        )

    # An empty result means the row was not found: a scan deregistered the
    # document between the listing and now. Not an error — the next pass will
    # simply not see it.
    return IndexDocumentOutput(
        nexus_id=input.nexus_id,
        outcome=OUTCOME_VANISHED,
        reason="Document is no longer registered.",
    )


def _is_workflow_fatal(exc: BaseException) -> bool:
    """Whether a failure is about the environment rather than this document.

    The distinction is whose fault the failure is. A note that cannot be parsed,
    embedded, or written is *this document's* problem: isolating it lets the rest
    of the batch through, and the document's own ``attempt_count`` decides whether
    it is tried again. A database that is down, a vault root that has vanished, or
    a programming error is *every* document's problem — isolating it would spend
    each remaining document's retry budget re-proving the same thing, and end with
    a whole vault marked failed for a reason that had nothing to do with the notes.

    Fatal:

    - ``VaultNotConfiguredError`` / ``VaultConfigurationError`` — the vault root is
      gone or unusable, so no document can be read.
    - ``OperationalError`` / ``InterfaceError`` / ``DBAPIError`` — the database
      connection itself is unusable; the next document cannot be written either.
    - ``MemoryError``, ``SystemError``, ``RecursionError`` — the process is unwell.
    - ``NameError``, ``ImportError``, ``AttributeError``, ``TypeError`` — an
      invariant or programming error. These must stay visible rather than being
      recorded as thousands of identical document failures.

    Not fatal (document-scoped):

    - ``VaultBoundaryError``, ``VaultExtensionError``, ``VaultFileTooLargeError`` —
      a security rejection *of this path*. Isolated deliberately: the boundary did
      its job, the document is refused and recorded, and nothing is swallowed —
      the reason is persisted and logged at exception level. Failing the whole run
      would let one bad filename stop a vault from indexing.
    - ``OSError`` — this file could not be read.
    - Provider and value errors — this note's content or a transient call.

    Args:
        exc: The exception that escaped the indexer.

    Returns:
        True if the workflow should fail rather than isolate the document.
    """
    from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError

    from nexus.obsidian.security import (
        VaultConfigurationError,
        VaultNotConfiguredError,
        VaultSecurityError,
    )

    # Configuration failures are environmental even though they are also
    # VaultSecurityError subclasses, so they are checked first.
    if isinstance(exc, (VaultNotConfiguredError, VaultConfigurationError)):
        return True
    # Every other vault-security rejection is about one path.
    if isinstance(exc, VaultSecurityError):
        return False
    if isinstance(exc, (OperationalError, InterfaceError, DBAPIError)):
        return True
    if isinstance(exc, (MemoryError, SystemError, RecursionError)):
        return True
    # OSError before the programming-error check: an unreadable file is this
    # document's problem, and OSError is not a programming error.
    if isinstance(exc, OSError):
        return False
    if isinstance(exc, (NameError, ImportError, AttributeError, TypeError)):
        return True
    return False


async def _record_isolated_failure(
    company_id: uuid.UUID, nexus_id: uuid.UUID, exc: BaseException
) -> None:
    """Persist a document-scoped failure on a fresh session.

    The session that raised has been rolled back, so the failure has to be written
    through a new one. Best-effort: if even this cannot be written the batch still
    continues, because the alternative is losing the remaining documents to a
    bookkeeping problem. The activity's return value still reports the failure, so
    it is never silent.
    """
    from nexus.database import async_session_factory
    from nexus.obsidian.indexer import VaultIndexer

    try:
        async with async_session_factory() as db:
            await VaultIndexer(db, company_id).record_failure(nexus_id, exc)
            await db.commit()
    except Exception:  # noqa: BLE001 - bookkeeping must not abort the batch
        logger.exception(
            "Could not record the failed status for document %s (company %s)",
            nexus_id,
            company_id,
        )


ALL_OBSIDIAN_ACTIVITIES = [
    list_pending_obsidian_documents_activity,
    index_obsidian_document_activity,
]
