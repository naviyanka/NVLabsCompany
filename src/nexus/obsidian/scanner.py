"""Vault scanner and document registration (ADR 0002 §17, Phase 1B-1).

Walks one company's vault through the read-only provider and reconciles what is
on disk against ``obsidian_documents``. Registration only: this module decides
which notes are new, changed, unchanged, moved, or gone, and keeps the registry
in step. It does not chunk, embed, or touch ``knowledge_chunks`` except to drop
chunks whose parent document has vanished — an orphaned chunk stays retrievable
through RAG search, which is how deleted content leaks back to users.

Identity, per this phase's read-only constraint:

- ``nexus_id`` is read from frontmatter when a human put one there, and honoured.
  Nothing is ever written back into a note file — Phase 1 has no write path, and
  minting an id into frontmatter would be one.
- Otherwise identity is ``(company_id, vault_path)``, which the unique index
  enforces.

The consequence is deliberate and bounded: for an untagged note, a MOVE or RENAME
is indistinguishable from a delete plus a create. The row is dropped and a fresh
one is registered under the new path, so the registry stays correct — only the
document's continuous history is lost. A note carrying a ``nexus_id`` in its
frontmatter is tracked across moves properly. Full move detection for every note
arrives with the write phase, which can mint ids into files.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.knowledge import SOURCE_TYPE_OBSIDIAN_DOCUMENT, KnowledgeChunk
from nexus.models.obsidian import INDEX_STATUS_STALE, ObsidianDocument
from nexus.obsidian.provider import ObsidianReader, VaultNote
from nexus.obsidian.security import VaultSecurityError, safe_reason

logger = logging.getLogger(__name__)

# ObsidianDocument column widths; frontmatter is human-authored, so a long title
# would otherwise fail the insert on PostgreSQL (SQLite would silently accept it).
_TITLE_MAX = 500
_DOC_TYPE_MAX = 50


@dataclass
class ScanResult:
    """What one scan found and did.

    Every list holds vault-relative paths, so a caller can report specifics
    without a second query.

    Attributes:
        created: Notes registered for the first time.
        updated: Notes whose content hash changed since the last scan.
        unchanged: Notes whose hash matched — no write was issued.
        moved: Notes matched by frontmatter ``nexus_id`` at a new path.
        deleted: Registry rows whose note is no longer in the vault.
        skipped: Notes that could not be read, each with the reason.
    """

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    moved: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)

    @property
    def seen(self) -> int:
        """Notes successfully read from the vault this scan."""
        return len(self.created) + len(self.updated) + len(self.unchanged) + len(self.moved)

    def counts(self) -> dict[str, int]:
        """A flat summary suitable for logging or an API response."""
        return {
            "created": len(self.created),
            "updated": len(self.updated),
            "unchanged": len(self.unchanged),
            "moved": len(self.moved),
            "deleted": len(self.deleted),
            "skipped": len(self.skipped),
            "seen": self.seen,
        }


class VaultScanner:
    """Reconciles one company's vault against ``obsidian_documents``.

    Example:
        >>> scanner = VaultScanner(db, company_id)
        >>> result = await scanner.scan()
        >>> result.counts()["created"]
        3
    """

    def __init__(
        self,
        db: AsyncSession,
        company_id: uuid.UUID,
        reader: ObsidianReader | None = None,
    ) -> None:
        """Bind a scanner to one company's vault and database session.

        Args:
            db: Async session. The scanner flushes but never commits — the caller
                owns the transaction boundary, so a partial scan rolls back whole
                rather than leaving the registry describing a vault state that
                never existed.
            company_id: The company whose vault is scanned. Passed to the reader,
                which derives the vault root from it, so a scanner can never
                reach another tenant's notes.
            reader: Optional reader override, for tests.
        """
        self._db = db
        self._company_id = company_id
        self._reader = reader or ObsidianReader(company_id)

    async def scan(self) -> ScanResult:
        """Walk the vault and bring the registry in step with it.

        A note that cannot be read — oversized, outside the vault boundary,
        unreadable — is recorded in ``skipped`` and the scan continues. One bad
        note must not hide the rest of the vault.

        Returns:
            A :class:`ScanResult` describing every classification.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
        """
        result = ScanResult()

        rows = await self._existing_rows()
        by_path = {row.vault_path: row for row in rows}
        by_id = {row.nexus_id: row for row in rows}
        matched: set[uuid.UUID] = set()
        claimed_ids: set[uuid.UUID] = set()

        for ref in self._reader.list_notes():
            try:
                note = self._reader.read_note(ref.vault_path)
            except (VaultSecurityError, OSError) as exc:
                # Includes FileNotFoundError: a note deleted mid-scan is simply
                # absent, and the next scan will drop its row. safe_reason
                # because these strings reach API clients, and an OSError
                # stringifies to the absolute host path it tried.
                logger.warning(
                    "Skipping %s for company %s: %s",
                    ref.vault_path,
                    self._company_id,
                    exc,
                )
                result.skipped.append((ref.vault_path, safe_reason(exc)))
                continue

            declared = _declared_id(note)
            # A duplicated id — two notes carrying the same frontmatter nexus_id,
            # usually a copy-paste — must not let the second note hijack the
            # first's row. Fall back to path identity for the loser.
            if declared is not None and declared in claimed_ids:
                result.skipped.append(
                    (note.vault_path, f"duplicate nexus_id {declared} already claimed")
                )
                continue

            row = None
            moved = False
            if declared is not None and declared in by_id:
                row = by_id[declared]
                moved = row.vault_path != note.vault_path
            elif note.vault_path in by_path:
                row = by_path[note.vault_path]

            if declared is not None:
                claimed_ids.add(declared)

            if row is None:
                self._register(note, declared)
                result.created.append(note.vault_path)
                continue

            matched.add(row.nexus_id)
            if moved:
                # Path is an attribute, not an identity: update it in place so the
                # document keeps its id, its history, and any chunks hanging off it.
                self._apply(row, note, moved=True)
                result.moved.append(note.vault_path)
            elif row.content_hash == note.content_hash:
                result.unchanged.append(note.vault_path)
            else:
                self._apply(row, note, moved=False)
                result.updated.append(note.vault_path)

        for row in rows:
            if row.nexus_id in matched:
                continue
            await self._deregister(row)
            result.deleted.append(row.vault_path)

        await self._db.flush()
        logger.info(
            "Obsidian vault scan for company %s: %s", self._company_id, result.counts()
        )
        return result

    async def _existing_rows(self) -> list[ObsidianDocument]:
        """Load this company's registry rows."""
        statement = select(ObsidianDocument).where(
            ObsidianDocument.company_id == self._company_id
        )
        return list((await self._db.execute(statement)).scalars().all())

    def _register(self, note: VaultNote, declared: uuid.UUID | None) -> None:
        """Insert a registry row for a newly seen note.

        A ``nexus_id`` a human wrote into frontmatter is honoured as the row's
        primary key, so the note keeps that identity across future moves.
        """
        row = ObsidianDocument(
            company_id=self._company_id,
            vault_path=note.vault_path,
            doc_type=_clip(note.parsed.doc_type, _DOC_TYPE_MAX),
            title=_clip(note.parsed.title, _TITLE_MAX) or _title_from_path(note.vault_path),
            content_hash=note.content_hash,
            mtime=note.mtime,
            # Registered, not yet chunked or embedded: indexing is a later phase,
            # and 'stale' is precisely "the registry knows this note, the index
            # does not".
            index_status=INDEX_STATUS_STALE,
        )
        if declared is not None:
            row.nexus_id = declared
        self._db.add(row)

    def _apply(self, row: ObsidianDocument, note: VaultNote, *, moved: bool) -> None:
        """Update a registry row from the note on disk."""
        row.vault_path = note.vault_path
        row.doc_type = _clip(note.parsed.doc_type, _DOC_TYPE_MAX)
        row.title = _clip(note.parsed.title, _TITLE_MAX) or _title_from_path(
            note.vault_path
        )
        row.content_hash = note.content_hash
        row.mtime = note.mtime
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        if not moved:
            # Content changed, so any chunks derived from it are stale. A pure
            # move leaves the body identical, so its index stays valid.
            row.index_status = INDEX_STATUS_STALE
            # New content is a new question, so it gets a fresh retry budget.
            # Without this, a document that exhausted its attempts on one bad
            # version would stay excluded from indexing even after a human fixed
            # the note.
            row.attempt_count = 0
            row.last_error = None
        self._db.add(row)

    async def _deregister(self, row: ObsidianDocument) -> None:
        """Drop a registry row whose note is gone, and any chunks derived from it.

        Chunks go first and in the same transaction. Nothing cascades from the
        polymorphic source pair (ADR 0002 §12), so a chunk left behind keeps
        deleted note content answerable through RAG search.
        """
        await self._db.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.company_id == self._company_id,
                KnowledgeChunk.source_type == SOURCE_TYPE_OBSIDIAN_DOCUMENT,
                KnowledgeChunk.source_id == row.nexus_id,
            )
        )
        await self._db.delete(row)


def _declared_id(note: VaultNote) -> uuid.UUID | None:
    """Return the note's frontmatter ``nexus_id``, if it is a usable UUID.

    A malformed id is ignored rather than fatal: the note falls back to path
    identity and still registers, which is better than refusing to index a note
    because someone typed its metadata by hand.
    """
    raw = note.parsed.nexus_id
    if raw is None:
        return None
    try:
        return uuid.UUID(str(raw))
    except (ValueError, AttributeError, TypeError):
        logger.debug(
            "Ignoring unparseable nexus_id %r in %s", raw, note.vault_path
        )
        return None


def _clip(value: str | None, limit: int) -> str | None:
    """Truncate a frontmatter string to its column width."""
    if value is None:
        return None
    return value[:limit]


def _title_from_path(vault_path: str) -> str:
    """Fall back to the filename stem, which is how Obsidian titles a note."""
    name = vault_path.rsplit("/", 1)[-1]
    stem = name[:-3] if name.lower().endswith(".md") else name
    return stem[:_TITLE_MAX]
