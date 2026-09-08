"""Filesystem trust boundary for the Obsidian vault (ADR 0002 §20).

Nothing else in NEXUS validates filesystem paths, so this module is the only
sanctioned way to turn a company id plus a caller-supplied relative path into a
path on disk. Every read routes through :func:`resolve_note_path`.

The threat model includes machine-generated paths, not only hostile users:
indexing walks filenames a human or an agent chose, so a note called
``../../etc/passwd`` is an expected input, not a surprise.

Phase 1 controls (all six from ADR 0002 §20):

1. Vault boundary  — the company root is the boundary; escape is refused.
2. Path traversal  — the resolved path must stay under that root.
3. Symlinks        — resolution happens before the boundary check.
4. Extensions      — ``.md`` only.
5. Size limits     — enforced before the file is opened.
6. Tenant isolation — the root is derived from ``company_id``, never passed in.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from nexus.config import settings

# ADR 0002 §20 control 4. Only Markdown is indexable; anything else is ignored
# rather than parsed.
ALLOWED_EXTENSIONS = frozenset({".md"})


class VaultSecurityError(Exception):
    """A path or file was refused by the vault trust boundary."""


class VaultNotConfiguredError(VaultSecurityError):
    """No vault root is configured, so no vault path can be produced."""


class VaultConfigurationError(VaultSecurityError):
    """A vault root is configured but unusable.

    Distinct from :class:`VaultNotConfiguredError`: an unset root means the
    integration is deliberately off, while an unusable one means someone meant
    to enable it and got it wrong.
    """


class VaultBoundaryError(VaultSecurityError):
    """The resolved path lies outside the company's vault root."""


class VaultExtensionError(VaultSecurityError):
    """The path does not carry an allowed extension."""


class VaultFileTooLargeError(VaultSecurityError):
    """The file exceeds the configured maximum note size."""


def vault_root() -> Path:
    """Return the configured vault root, fully resolved.

    Returns:
        The resolved root directory holding every company vault.

    Raises:
        VaultNotConfiguredError: If ``obsidian_vault_root`` is unset.
    """
    configured = (settings.obsidian_vault_root or "").strip()
    if not configured:
        raise VaultNotConfiguredError(
            "obsidian_vault_root is not configured; the Obsidian integration is disabled"
        )
    # strict=False so a not-yet-created root still resolves; existence is
    # checked by callers that need to read.
    return Path(configured).expanduser().resolve(strict=False)


def is_vault_enabled() -> bool:
    """Return whether an Obsidian vault is configured at all.

    The single place the setting is read for an enablement check, so callers that
    only need to know "is this integration on" do not reach for the raw setting
    and get flagged by arch_guard R6.
    """
    return bool((settings.obsidian_vault_root or "").strip())


def validate_vault_root() -> Path | None:
    """Check the configured vault root at startup, or explain why it is unusable.

    A typo'd root would otherwise resolve fine and simply contain no notes, so
    every scan would report an empty vault as though that were a valid state.
    That is the failure this function exists to prevent: the integration either
    starts with a real vault or refuses to start.

    Returns:
        The resolved vault root, or None when the integration is disabled
        (``obsidian_vault_root`` unset), which is the default and not an error.

    Raises:
        VaultConfigurationError: If a root is configured but does not exist, is
            not a directory, cannot be canonicalized, or cannot be read.
    """
    configured = (settings.obsidian_vault_root or "").strip()
    if not configured:
        return None

    try:
        # strict=True so a nonexistent path raises here rather than resolving to
        # a plausible-looking path that is simply not there.
        root = Path(configured).expanduser().resolve(strict=True)
    except OSError as exc:
        raise VaultConfigurationError(
            f"obsidian_vault_root {configured!r} cannot be resolved: {exc}. "
            f"Point it at an existing directory, or unset it to disable the "
            f"Obsidian integration."
        ) from exc

    if not root.is_dir():
        raise VaultConfigurationError(
            f"obsidian_vault_root {configured!r} is not a directory (resolved to "
            f"{root}). It must be the directory holding one subdirectory per "
            f"company vault."
        )

    if not os.access(root, os.R_OK | os.X_OK):
        raise VaultConfigurationError(
            f"obsidian_vault_root {root} is not readable by this process."
        )

    limit = settings.obsidian_max_note_bytes
    if not isinstance(limit, int) or limit <= 0:
        raise VaultConfigurationError(
            f"obsidian_max_note_bytes must be a positive integer, got {limit!r}."
        )

    return root


def company_vault_root(company_id: uuid.UUID) -> Path:
    """Return the vault root for one company.

    Tenant isolation is this path, not a per-read authorization check (ADR 0002
    §15): a caller who cannot name the company cannot reach its notes.

    Args:
        company_id: The company whose vault root is wanted.

    Returns:
        ``<obsidian_vault_root>/<company_id>``, resolved.

    Raises:
        VaultNotConfiguredError: If no vault root is configured.
        VaultBoundaryError: If ``company_id`` is not a UUID. The type annotation
            is not a runtime guard, and this value is interpolated straight into
            a filesystem path: a caller passing the string ``"../.."`` would
            otherwise walk out of the vault root entirely.
    """
    try:
        company = uuid.UUID(str(company_id))
    except (ValueError, AttributeError, TypeError) as exc:
        raise VaultBoundaryError(
            f"company_id must be a UUID, got {company_id!r}"
        ) from exc
    return (vault_root() / str(company)).resolve(strict=False)


def resolve_note_path(company_id: uuid.UUID, relative_path: str) -> Path:
    """Resolve a vault-relative note path, refusing anything outside the vault.

    Symlinks are resolved *before* the boundary comparison, so a link inside the
    vault pointing outside it is refused rather than followed.

    Args:
        company_id: The company whose vault is being read.
        relative_path: Path relative to that company's vault root, e.g.
            ``"Knowledge/SSRF Protection.md"``.

    Returns:
        The absolute, resolved path, guaranteed to be under the company root and
        to carry an allowed extension.

    Raises:
        VaultNotConfiguredError: If no vault root is configured.
        VaultBoundaryError: If the path escapes the company vault root, or is
            absolute.
        VaultExtensionError: If the extension is not allowed.
    """
    root = company_vault_root(company_id)

    candidate = Path(relative_path)
    if candidate.is_absolute() or candidate.drive or candidate.root:
        # An absolute path ignores the root entirely, so refuse it outright
        # rather than trying to reinterpret it as relative.
        raise VaultBoundaryError(
            f"vault paths must be relative to the company vault root: {relative_path!r}"
        )

    resolved = (root / candidate).resolve(strict=False)

    if resolved != root and root not in resolved.parents:
        raise VaultBoundaryError(
            f"resolved path escapes the company vault root: {relative_path!r}"
        )

    if resolved.suffix.lower() not in ALLOWED_EXTENSIONS:
        raise VaultExtensionError(
            f"extension {resolved.suffix!r} is not indexable; allowed: "
            f"{sorted(ALLOWED_EXTENSIONS)}"
        )

    return resolved


def check_size(path: Path) -> int:
    """Check a file against the configured size cap before it is opened.

    Args:
        path: An already-resolved path from :func:`resolve_note_path`.

    Returns:
        The file size in bytes.

    Raises:
        VaultFileTooLargeError: If the file exceeds ``obsidian_max_note_bytes``.
        OSError: If the file cannot be stat'ed.
    """
    size = path.stat().st_size
    limit = settings.obsidian_max_note_bytes
    if size > limit:
        raise VaultFileTooLargeError(
            f"note is {size} bytes, over the {limit}-byte limit: {path.name}"
        )
    return size


def safe_reason(exc: BaseException) -> str:
    """Describe a vault failure without disclosing host filesystem layout.

    Reasons recorded during a scan or an index pass are returned to API clients,
    so they must not carry an absolute path. The OS supplies them freely —
    ``FileNotFoundError`` stringifies to the full path it tried — while this
    package's own :class:`VaultSecurityError` messages already reference only a
    vault-relative path or a bare filename, which the caller authored and
    already knows.

    Args:
        exc: The exception to describe.

    Returns:
        For a :class:`VaultSecurityError`, ``"Type: message"``. For anything
        else, the exception type name alone.
    """
    if isinstance(exc, VaultSecurityError):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


def is_allowed_extension(path: Path | str) -> bool:
    """Return whether a path carries an indexable extension.

    Used when walking the vault, where a non-Markdown file is skipped quietly
    rather than treated as an error.

    Args:
        path: Any path or path-like string.

    Returns:
        True if the suffix is in :data:`ALLOWED_EXTENSIONS`.
    """
    return Path(path).suffix.lower() in ALLOWED_EXTENSIONS
