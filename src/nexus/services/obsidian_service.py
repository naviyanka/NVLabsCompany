"""Operator-facing service over the Obsidian vault scanner (ADR 0002, Phase 1B-2).

Sits between the HTTP route and :class:`~nexus.obsidian.scanner.VaultScanner`,
owning the two things a route must not: per-company scan serialization, and the
translation of vault errors into outcomes a caller can act on.

The scanner keeps every other responsibility — filesystem access, identity,
reconciliation, hashing, security, metadata. Nothing here reads the vault.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from nexus.obsidian.indexer import IndexResult, VaultIndexer
from nexus.obsidian.scanner import ScanResult, VaultScanner
from nexus.obsidian.security import (
    VaultConfigurationError,
    VaultNotConfiguredError,
    company_vault_root,
    is_vault_enabled,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Integration states reported by `status`.
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_AVAILABLE = "available"
STATUS_UNAVAILABLE = "unavailable"

# One lock per company covering BOTH scan and index. They are not independent:
# a scan can deregister a document and delete its chunks while an index pass is
# mid-reindex of that same document, so serializing only scans against scans
# would leave the sharper race open. Different companies proceed concurrently,
# which is why this is keyed rather than global.
#
# In-process only, and deliberately so: both operations are idempotent and their
# writes are transactional, so the worst a second replica can do is duplicate
# work and lose a race on the unique (company_id, vault_path) index. Redis is
# already available for cross-replica locking (governance/leader_election.py) and
# remains the upgrade path if operators ever run these across replicas.
_scan_locks: dict[uuid.UUID, asyncio.Lock] = {}


def _lock_for(company_id: uuid.UUID) -> asyncio.Lock:
    """Return this company's vault-operation lock, creating it on first use."""
    lock = _scan_locks.get(company_id)
    if lock is None:
        lock = asyncio.Lock()
        _scan_locks[company_id] = lock
    return lock


class ObsidianServiceError(Exception):
    """Base for vault-service failures that a caller can be told about."""


class VaultUnavailableError(ObsidianServiceError):
    """A vault is configured but cannot be read right now."""


class ScanInProgressError(ObsidianServiceError):
    """A scan or index pass for this company is already running.

    One exception for both because they share one lock: from the caller's side
    the actionable fact is "this company's vault is busy, retry later", not which
    of the two operations holds it.
    """


@dataclass(frozen=True)
class VaultStatus:
    """Non-sensitive view of the integration's state.

    Attributes:
        state: One of ``not_configured``, ``available``, ``unavailable``.
        configured: Whether a vault root is set at all.
        vault_present: Whether this company's vault directory exists on disk.
        indexed_documents: Registry row count for this company.
        detail: Operator-facing explanation when the state is not available.
    """

    state: str
    configured: bool
    vault_present: bool
    indexed_documents: int
    detail: str | None = None


class ObsidianVaultService:
    """Scan and status operations for one company's vault."""

    def __init__(self, db: AsyncSession, company_id: uuid.UUID) -> None:
        """Bind the service to a session and an authorized company.

        Args:
            db: Async session. The service flushes through the scanner and never
                commits — the caller owns the transaction, so a failed scan
                leaves no registry rows behind.
            company_id: The company to operate on. Comes from the authenticated
                principal, never from a request body, so the vault root is not
                client-selectable.
        """
        self._db = db
        self._company_id = company_id

    async def status(self) -> VaultStatus:
        """Report whether the integration is usable, without scanning.

        Counts registry rows rather than walking the vault: a status check must
        stay cheap enough to poll.

        Returns:
            A :class:`VaultStatus`. Never raises for a misconfigured vault — the
            misconfiguration *is* the answer.
        """
        indexed = await self._document_count()

        if not is_vault_enabled():
            return VaultStatus(
                state=STATUS_NOT_CONFIGURED,
                configured=False,
                vault_present=False,
                indexed_documents=indexed,
                detail="No Obsidian vault root is configured.",
            )

        try:
            present = company_vault_root(self._company_id).is_dir()
        except (VaultNotConfiguredError, VaultConfigurationError, OSError) as exc:
            logger.warning(
                "Obsidian vault root unusable for company %s: %s", self._company_id, exc
            )
            return VaultStatus(
                state=STATUS_UNAVAILABLE,
                configured=True,
                vault_present=False,
                indexed_documents=indexed,
                detail="The configured vault root is not usable on this host.",
            )

        if not present:
            return VaultStatus(
                state=STATUS_UNAVAILABLE,
                configured=True,
                vault_present=False,
                indexed_documents=indexed,
                detail="No vault directory exists for this company yet.",
            )

        return VaultStatus(
            state=STATUS_AVAILABLE,
            configured=True,
            vault_present=True,
            indexed_documents=indexed,
        )

    async def scan(self) -> ScanResult:
        """Reconcile the vault against the registry, once, serialized per company.

        Returns:
            The scanner's own :class:`ScanResult`.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
            VaultUnavailableError: If the vault cannot be read.
            ScanInProgressError: If this company already has a scan or index
                running.
        """
        return await self._exclusive(
            "scan", lambda: VaultScanner(self._db, self._company_id).scan()
        )

    async def index(self, limit: int | None = None) -> IndexResult:
        """Chunk and embed every document the scanner left stale.

        Takes the same per-company lock as :meth:`scan`, so an index pass cannot
        run while a scan is deregistering documents and deleting their chunks.

        Args:
            limit: Optional cap on documents processed, so a large first index
                can be run in batches rather than one long transaction.

        Returns:
            The indexer's own :class:`IndexResult`.

        Raises:
            VaultNotConfiguredError: If no vault root is configured.
            VaultUnavailableError: If the vault cannot be read.
            ScanInProgressError: If this company already has a scan or index
                running.
        """
        return await self._exclusive(
            "index",
            lambda: VaultIndexer(self._db, self._company_id).index_stale(limit=limit),
        )

    async def _exclusive(
        self, operation: str, run: Callable[[], Awaitable[_T]]
    ) -> _T:
        """Run one vault operation under this company's lock.

        Shared by scan and index because the preconditions and the error mapping
        are identical: the integration must be configured, no sibling operation
        may be in flight, and a filesystem failure becomes
        :class:`VaultUnavailableError` with the detail kept to the logs.
        """
        if not is_vault_enabled():
            raise VaultNotConfiguredError(
                f"No Obsidian vault root is configured; nothing to {operation}."
            )

        lock = _lock_for(self._company_id)
        if lock.locked():
            raise ScanInProgressError(
                f"A vault operation is already running for company {self._company_id}."
            )

        async with lock:
            try:
                return await run()
            except (VaultNotConfiguredError, ScanInProgressError):
                raise
            except (VaultConfigurationError, OSError) as exc:
                # The vault is configured but the filesystem disagrees — root
                # removed, permissions changed, volume unmounted.
                logger.exception(
                    "Obsidian vault %s failed for company %s",
                    operation,
                    self._company_id,
                )
                raise VaultUnavailableError(
                    "The vault could not be read. Check the server logs."
                ) from exc

    async def _document_count(self) -> int:
        """Registry rows for this company."""
        from sqlalchemy import func, select

        from nexus.models.obsidian import ObsidianDocument

        statement = select(func.count()).select_from(ObsidianDocument).where(
            ObsidianDocument.company_id == self._company_id
        )
        return int((await self._db.execute(statement)).scalar_one())
