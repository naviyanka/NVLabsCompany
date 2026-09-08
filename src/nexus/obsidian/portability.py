"""Vault content in company export and import (ADR 0002 §19).

``CompanyPortabilityService`` walks database tables. It cannot see a filesystem,
so a vault-backed note body silently drops out of an export — and §19 says
silence is not an option. Phase 1 was allowed to represent the gap in the
manifest; §19 requires the files themselves *before* any write phase, because
from that point the vault holds content that exists nowhere else.

This module is the file half. It is deliberately separate from
``portability_service.py``: that module is generic table machinery, and giving it
filesystem knowledge would put path validation in a place with no vault context.

Everything crosses as **vault-relative** paths. The vault root is host layout and
never appears in an archive — an archive is portable, and a path like
``C:\\Users\\...\\Vault`` is neither portable nor anyone else's business.

Rules, each because a specific thing would otherwise go wrong:

- **Only ``.md`` files.** The extension allowlist is the same one indexing uses
  (§20 control 4). A vault directory may contain anything a human dropped there;
  an export is not a backup tool.
- **Every path re-validated on import.** An archive is untrusted input — it may
  have been edited, or produced by another system. Each path goes back through
  ``resolve_note_path``, so traversal, absolute paths, drive-relative paths, UNC
  paths and symlink escapes are refused on the way in as well as on the way out.
- **``.obsidian/`` is excluded.** It holds editor configuration — window layout,
  installed plugins, hotkeys, theme — not company knowledge. It is per-machine
  state that would arrive at the destination describing a workspace that does not
  exist there. Excluded explicitly rather than by extension, so the reason is
  recorded and the manifest can say so.
- **Git metadata is excluded.** ``.git/`` is the vault's history, and §18 makes
  that the vault repository's business. Packing object files into a company
  archive would make history a row in someone's database.
- **Symlinks are not followed.** A link is skipped rather than dereferenced, so an
  export cannot be tricked into reading outside the vault by a link inside it.
- **Size is bounded per file and in total.** An export runs in a request; an
  unbounded read of an arbitrary directory is a denial-of-service surface.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from nexus.config import settings
from nexus.obsidian.security import (
    ALLOWED_EXTENSIONS,
    VaultSecurityError,
    company_vault_root,
    is_vault_enabled,
    resolve_note_path,
)

logger = logging.getLogger(__name__)

# Directory names never exported. Editor state and Git history are not company
# knowledge; see the module docstring for why each is named rather than filtered
# by extension.
EXCLUDED_DIRECTORIES = frozenset({".obsidian", ".git", ".trash", ".stfolder"})

# Total bytes of note content one export will carry. A vault larger than this
# needs a file-level transfer, not a JSON archive, and the manifest says so
# rather than truncating quietly.
MAX_EXPORT_TOTAL_BYTES = 64 * 1024 * 1024


@dataclass
class VaultBundle:
    """The vault half of a company archive.

    Attributes:
        files: Vault-relative path to UTF-8 note text.
        skipped: Vault-relative path to the reason it was left out, so an
            incomplete export is legible rather than silent.
        complete: False when anything was skipped or a limit was reached. An
            importer can then refuse to present the result as a full restore.
        detail: A short operator-facing summary.
    """

    files: dict[str, str] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    complete: bool = True
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        """The archive representation. Vault-relative paths only."""
        return {
            "files": dict(sorted(self.files.items())),
            "skipped": dict(sorted(self.skipped.items())),
            "complete": self.complete,
            "detail": self.detail,
            "file_count": len(self.files),
            "total_bytes": sum(len(text.encode("utf-8")) for text in self.files.values()),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object] | None) -> VaultBundle:
        """Rebuild a bundle from an archive, tolerating an archive without one.

        An archive produced before vault export existed has no bundle. That is an
        empty bundle, not an error — but it is marked incomplete, because the
        company it came from may well have had notes.
        """
        if not data:
            return cls(complete=False, detail="This archive carries no vault content.")
        raw_files = data.get("files") or {}
        raw_skipped = data.get("skipped") or {}
        return cls(
            files={
                str(path): str(text)
                for path, text in dict(raw_files).items()  # type: ignore[arg-type]
            },
            skipped={
                str(path): str(reason)
                for path, reason in dict(raw_skipped).items()  # type: ignore[arg-type]
            },
            complete=bool(data.get("complete", False)),
            detail=str(data.get("detail", "")),
        )


def export_vault_files(company_id: uuid.UUID) -> VaultBundle:
    """Collect one company's note files as vault-relative text.

    Tenant isolation is the walk root: the directory comes from
    ``company_vault_root``, so an export cannot reach another company's notes.

    Args:
        company_id: The company whose vault to export.

    Returns:
        A :class:`VaultBundle`. A company with no vault yields an empty complete
        bundle — nothing was omitted, there was nothing there.
    """
    bundle = VaultBundle()

    if not is_vault_enabled():
        bundle.detail = "No Obsidian vault is configured, so no notes were exported."
        return bundle

    try:
        root = company_vault_root(company_id)
    except VaultSecurityError as exc:
        bundle.complete = False
        bundle.detail = f"Vault root unusable: {type(exc).__name__}"
        return bundle

    if not root.is_dir():
        bundle.detail = "This company has no vault directory."
        return bundle

    max_note_bytes = settings.obsidian_max_note_bytes
    total = 0

    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()

        if any(part in EXCLUDED_DIRECTORIES for part in path.relative_to(root).parts[:-1]):
            continue
        if path.name in EXCLUDED_DIRECTORIES or path.is_dir():
            continue
        if path.is_symlink():
            # Not followed: a link inside the vault may point outside it, and an
            # export must not be the thing that reads there.
            bundle.skipped[relative] = "symlink"
            bundle.complete = False
            continue
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            bundle.skipped[relative] = "not a Markdown note"
            bundle.complete = False
            continue

        try:
            size = path.stat().st_size
            if size > max_note_bytes:
                bundle.skipped[relative] = "over the note size limit"
                bundle.complete = False
                continue
            if total + size > MAX_EXPORT_TOTAL_BYTES:
                bundle.skipped[relative] = "export size limit reached"
                bundle.complete = False
                continue
            bundle.files[relative] = path.read_text(encoding="utf-8")
            total += size
        except (OSError, UnicodeDecodeError) as exc:
            # A note that cannot be read is recorded, not fatal: one unreadable
            # file must not cost a company its whole export.
            bundle.skipped[relative] = type(exc).__name__
            bundle.complete = False

    if bundle.complete:
        bundle.detail = f"{len(bundle.files)} note(s) exported."
    else:
        bundle.detail = (
            f"{len(bundle.files)} note(s) exported, {len(bundle.skipped)} omitted. "
            "This export is partial."
        )
    return bundle


def import_vault_files(
    company_id: uuid.UUID, bundle: VaultBundle, *, overwrite: bool = False
) -> dict[str, str]:
    """Restore note files into one company's vault.

    Every path is re-validated through the §20 validator against the *destination*
    company's root, so an archive cannot place a file outside the vault it is
    being imported into — not by traversal, not by an absolute path, not by a UNC
    path, and not through a symlinked parent directory.

    Existing files are kept by default. An import that silently overwrote a note
    would destroy content that, after the write phase, exists nowhere else.

    Args:
        company_id: The destination company. Its vault root is where files land.
        bundle: The bundle to restore.
        overwrite: Replace an existing note rather than skipping it.

    Returns:
        Vault-relative path to outcome: ``"restored"``, ``"exists"``, or a
        refusal reason. Refusals are reported rather than raised, so one bad path
        in an archive does not abort the rest of the restore.
    """
    outcomes: dict[str, str] = {}

    if not bundle.files:
        return outcomes

    root = company_vault_root(company_id)

    for relative, text in sorted(bundle.files.items()):
        if any(part in EXCLUDED_DIRECTORIES for part in Path(relative).parts):
            outcomes[relative] = "refused: excluded directory"
            continue
        try:
            # The security boundary, applied to untrusted archive input.
            destination = resolve_note_path(company_id, relative)
        except VaultSecurityError as exc:
            outcomes[relative] = f"refused: {type(exc).__name__}"
            continue

        # A parent directory that is a symlink would land the file outside the
        # vault even though the joined path looks contained.
        if any(
            parent.is_symlink()
            for parent in destination.parents
            if root in parent.parents or parent == root
        ):
            outcomes[relative] = "refused: symlinked parent directory"
            continue

        if destination.exists() and not overwrite:
            outcomes[relative] = "exists"
            continue

        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Atomic, the same pattern the write phase will use (§20 control 11):
            # a reader sees the old file or the new one, never a partial write.
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            temporary.write_text(text, encoding="utf-8")
            import os

            os.replace(temporary, destination)
            outcomes[relative] = "restored"
        except OSError as exc:
            outcomes[relative] = f"failed: {type(exc).__name__}"

    return outcomes
