"""Read-only Obsidian vault provider (ADR 0002 §23).

Phase 1 is read-only: `list`, `read`, and nothing else. There is no create,
update, append, move, or delete here, and none is added until the write phase
brings the controls in ADR 0002 §20 items 7-13 (secret scanning, approval
gates, atomic writes, conflict handling, rollback, write authorization).

Every path this module touches comes from
:func:`nexus.obsidian.security.resolve_note_path`, which is the trust boundary.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from nexus.obsidian.frontmatter import ParsedNote, parse_note
from nexus.obsidian.security import (
    VaultSecurityError,
    check_size,
    company_vault_root,
    is_allowed_extension,
    resolve_note_path,
)


@dataclass(frozen=True)
class VaultNoteRef:
    """A note found while listing a vault, without its body.

    Attributes:
        vault_path: POSIX path relative to the company vault root.
        size_bytes: File size on disk.
        mtime: Last modification time, naive UTC to match the model columns.
    """

    vault_path: str
    size_bytes: int
    mtime: datetime


@dataclass(frozen=True)
class VaultNote:
    """A note read from the vault.

    Attributes:
        vault_path: POSIX path relative to the company vault root.
        parsed: Frontmatter metadata plus the markdown body.
        content_hash: SHA-256 of the raw file text, for change detection.
        mtime: Last modification time, naive UTC.
        size_bytes: File size on disk.
    """

    vault_path: str
    parsed: ParsedNote
    content_hash: str
    mtime: datetime
    size_bytes: int


def content_hash(text: str) -> str:
    """Return the SHA-256 hex digest of note text.

    Hashing the text rather than the bytes on disk keeps the digest stable
    across line-ending differences introduced by editors on other platforms,
    which would otherwise show up as spurious changes on every scan.

    Args:
        text: Raw note text.

    Returns:
        A 64-character hex digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ObsidianReader:
    """Read-only access to one company's vault.

    Example:
        >>> reader = ObsidianReader(company_id)
        >>> for ref in reader.list_notes():
        ...     note = reader.read_note(ref.vault_path)
    """

    def __init__(self, company_id: uuid.UUID) -> None:
        """Bind a reader to one company's vault.

        Args:
            company_id: The company whose vault this reader may read. Every
                path is resolved under this company's root, so one reader can
                never reach another tenant's notes.
        """
        self._company_id = company_id

    @property
    def company_id(self) -> uuid.UUID:
        """The company this reader is bound to."""
        return self._company_id

    def root(self) -> Path:
        """Return this company's vault root.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
        """
        return company_vault_root(self._company_id)

    def exists(self) -> bool:
        """Return whether this company's vault directory exists on disk.

        A configured-but-absent vault is a normal state — the company has not
        created one yet — so this is a question, not an error.
        """
        try:
            return self.root().is_dir()
        except VaultSecurityError:
            return False

    def list_notes(self) -> list[VaultNoteRef]:
        """List every indexable note in the vault, recursively.

        Non-Markdown files are skipped quietly (ADR 0002 §20 control 4).
        Obsidian's own ``.obsidian/`` configuration directory and any other
        dot-directory are skipped: they hold editor state, not knowledge.

        Every candidate is re-resolved through :func:`resolve_note_path`, so the
        listing applies the same boundary the read path does. Without that, a
        symlink or Windows junction inside the vault pointing at another
        company's vault would have its target's filename, size, and mtime
        returned here — the read would be refused later, but the metadata would
        already have leaked.

        Files that cannot be stat'ed or that fail the boundary are skipped rather
        than failing the scan, so one bad entry does not hide the rest of the
        vault.

        Returns:
            Note references sorted by ``vault_path`` for a stable scan order.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
        """
        root = self.root()
        if not root.is_dir():
            return []

        refs: list[VaultNoteRef] = []
        for path in root.rglob("*"):
            if any(part.startswith(".") for part in path.relative_to(root).parts):
                continue
            if not is_allowed_extension(path):
                continue
            relative = path.relative_to(root).as_posix()
            try:
                # Re-resolve through the boundary: an entry whose real target is
                # outside this company's vault must not be listed at all.
                resolved = resolve_note_path(self._company_id, relative)
                if not resolved.is_file():
                    continue
                stat = resolved.stat()
            except (VaultSecurityError, OSError):
                continue
            refs.append(
                VaultNoteRef(
                    vault_path=relative,
                    size_bytes=stat.st_size,
                    mtime=_naive_utc(stat.st_mtime),
                )
            )

        refs.sort(key=lambda ref: ref.vault_path)
        return refs

    def read_note(self, vault_path: str) -> VaultNote:
        """Read and parse one note.

        Args:
            vault_path: Path relative to the company vault root.

        Returns:
            The parsed note with its content hash and mtime.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
            VaultBoundaryError: If the path escapes the vault root.
            VaultExtensionError: If the path is not Markdown.
            VaultFileTooLargeError: If the file exceeds the size cap.
            FileNotFoundError: If the note does not exist.
            OSError: If the file cannot be read.
        """
        resolved = resolve_note_path(self._company_id, vault_path)

        # Size is checked before the read so an oversized file is never loaded
        # into memory. stat() raising FileNotFoundError here is the intended
        # signal for a missing note.
        size = check_size(resolved)
        stat = resolved.stat()
        text = resolved.read_text(encoding="utf-8", errors="replace")

        return VaultNote(
            vault_path=resolved.relative_to(self.root()).as_posix(),
            parsed=parse_note(text),
            content_hash=content_hash(text),
            mtime=_naive_utc(stat.st_mtime),
            size_bytes=size,
        )


def _naive_utc(timestamp: float) -> datetime:
    """Convert an epoch timestamp to naive UTC.

    The model columns are naive datetimes in UTC (matching every other table in
    this schema), so tz-aware values would compare unequal against stored rows.
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)
