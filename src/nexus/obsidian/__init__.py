"""Obsidian vault integration (ADR 0002).

Phase 1 is read-only. The vault owns note bodies; PostgreSQL owns identity,
index state, and every derived retrieval representation.

Components:
    - security: the filesystem trust boundary — the only way to resolve a path
    - frontmatter: YAML frontmatter extraction ahead of MarkdownParser
    - provider: ObsidianReader, read-only list and read
    - scanner: VaultScanner, reconciles the vault against obsidian_documents
    - indexer: VaultIndexer, chunks and embeds stale documents through RAGPipeline
    - wikilinks: [[target]] extraction, the vault's own relationship mechanism
    - embedding_policy: 1536-dimension enforcement at configuration load

Writeback controls (Phase 1G). The writer only replaces existing notes after
secret scanning, path authorization, conflict detection, approval checks, and
atomic replacement. It does not create, delete, move, merge, or commit Git changes.
"""

from nexus.obsidian.actor import (
    ACTOR_AGENT,
    ACTOR_OPERATOR,
    ACTOR_SYSTEM,
    ActorError,
    WriteActor,
)
from nexus.obsidian.authorization import (
    WHOLE_VAULT,
    VaultAuthorizationError,
    VaultWriteAuthorizer,
    VaultWriteGrant,
    canonical_vault_path,
    normalize_subtree,
)
from nexus.obsidian.writer import (
    ObsidianWriteError,
    ObsidianWriter,
    WriteApprovalError,
    WriteConflictError,
    WriteContentError,
    WriteRecoveryError,
    WriteResult,
)
from nexus.obsidian.embedding_policy import (
    EmbeddingPolicyError,
    validate_embedding_policy,
)
from nexus.obsidian.portability import (
    EXCLUDED_DIRECTORIES,
    VaultBundle,
    export_vault_files,
    import_vault_files,
)
from nexus.obsidian.secret_scan import (
    SCAN_CLEAN,
    SCAN_SCANNER_ERROR,
    SCAN_SECRET_DETECTED,
    SecretScanResult,
    scan_bytes,
    scan_text,
)
from nexus.obsidian.vault_git import (
    GIT_ABSENT,
    GIT_CLEAN,
    GIT_DIRTY,
    GIT_ERROR,
    GIT_UNAVAILABLE,
    VaultGitStatus,
    rollback_plan,
    vault_git_status,
)
from nexus.obsidian.frontmatter import ParsedNote, parse_note
from nexus.obsidian.provider import ObsidianReader, VaultNote, VaultNoteRef, content_hash
from nexus.obsidian.indexer import IndexResult, VaultIndexer
from nexus.obsidian.scanner import ScanResult, VaultScanner
from nexus.obsidian.security import (
    ALLOWED_EXTENSIONS,
    VaultBoundaryError,
    VaultConfigurationError,
    VaultExtensionError,
    VaultFileTooLargeError,
    VaultNotConfiguredError,
    VaultSecurityError,
    check_size,
    company_vault_root,
    is_allowed_extension,
    resolve_note_path,
    safe_reason,
    validate_vault_root,
    vault_root,
)
from nexus.obsidian.wikilinks import (
    MAX_LINKS_PER_NOTE,
    extract_wikilinks,
    frontmatter_links,
    note_links,
)

__all__ = [
    # Security boundary
    "ALLOWED_EXTENSIONS",
    "VaultSecurityError",
    "VaultNotConfiguredError",
    "VaultConfigurationError",
    "VaultBoundaryError",
    "VaultExtensionError",
    "VaultFileTooLargeError",
    "vault_root",
    "validate_vault_root",
    "company_vault_root",
    "resolve_note_path",
    "check_size",
    "is_allowed_extension",
    "safe_reason",
    # Frontmatter
    "ParsedNote",
    "parse_note",
    # Read-only provider
    "ObsidianReader",
    "VaultNote",
    "VaultNoteRef",
    "content_hash",
    # Scanner / document registration
    "VaultScanner",
    "ScanResult",
    # Indexing engine
    "VaultIndexer",
    "IndexResult",
    # Wikilinks
    "MAX_LINKS_PER_NOTE",
    "extract_wikilinks",
    "frontmatter_links",
    "note_links",
    # Embedding policy
    "EmbeddingPolicyError",
    "validate_embedding_policy",
    # Writeback preconditions (ADR 0002 §20 controls 7, 9, 12, 13; §19).
    # None of these write to the vault — they are what a writer must clear first.
    "SCAN_CLEAN",
    "SCAN_SECRET_DETECTED",
    "SCAN_SCANNER_ERROR",
    "SecretScanResult",
    "scan_bytes",
    "scan_text",
    "WHOLE_VAULT",
    "VaultAuthorizationError",
    "VaultWriteAuthorizer",
    "VaultWriteGrant",
    "canonical_vault_path",
    "normalize_subtree",
    "ACTOR_AGENT",
    "ACTOR_SYSTEM",
    "ACTOR_OPERATOR",
    "ActorError",
    "WriteActor",
    "GIT_ABSENT",
    "GIT_CLEAN",
    "GIT_DIRTY",
    "GIT_UNAVAILABLE",
    "GIT_ERROR",
    "VaultGitStatus",
    "vault_git_status",
    "rollback_plan",
    "EXCLUDED_DIRECTORIES",
    "VaultBundle",
    "export_vault_files",
    "import_vault_files",
    "ObsidianWriter",
    "ObsidianWriteError",
    "WriteApprovalError",
    "WriteConflictError",
    "WriteContentError",
    "WriteRecoveryError",
    "WriteResult",
]
