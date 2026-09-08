"""Per-agent, per-path write authorization for the vault (ADR 0002 §20 control 13).

``ToolRegistry.grant_access(agent_id, tool_id)`` answers "may this agent use the
vault write tool at all". It cannot answer "may it write *this note*", which is
the question control 13 actually poses: one write tool, many agents, and each
confined to its own subtree.

**Option A, composed rather than replaced.** The tool-level gate stays where it
is — this module calls ``has_access`` rather than reimplementing it — and adds the
path dimension on top. A parallel Obsidian-only authorization system would give
the same agent two unrelated permission stores, and revoking the tool would leave
its path grants behind looking authoritative.

The decision chain, in order, because each step is meaningless without the one
before it:

    company   →  the vault root (tenant isolation is the path itself, §15)
    agent     →  a tool grant in ToolRegistry (control 13's coarse half)
    tool      →  the vault write tool specifically
    subtree   →  the canonical vault-relative path

**Authorization runs on the canonical path, never the requested one.** The raw
string goes through ``resolve_note_path`` first, so ``Projects/../Secrets/K.md``
is authorized as ``Secrets/K.md`` and refused, rather than being compared as text
and allowed on its ``Projects/`` prefix. A check against an unnormalized path is
the classic confused-deputy bug in exactly this shape.

Nothing here writes. There is no writer yet (Phase 1F-PRE), and this module is
one of its preconditions.

**Persistence.** Path grants live in ``vault_write_grants``. Every async
authorization reads current active rows, so API replicas and temporal workers use
the same authority. No writer exists yet.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from nexus.models.obsidian import VaultWriteGrantRecord

from nexus.obsidian.security import (
    VaultBoundaryError,
    VaultSecurityError,
    company_vault_root,
    resolve_note_path,
)

logger = logging.getLogger(__name__)

# The subtree token meaning "this company's whole vault". Spelled explicitly so a
# broad grant is visible in a grant listing rather than being an empty string.
WHOLE_VAULT = "*"


class VaultAuthorizationError(Exception):
    """A write was refused because the actor is not authorized for that path."""


@dataclass(frozen=True)
class VaultWriteGrant:
    """One agent's authority to write under one subtree of one company's vault.

    Attributes:
        company_id: The company whose vault this grant applies to. A grant never
            spans companies: the vault root is derived from this id.
        agent_id: The agent the grant is for.
        tool_id: The write tool the grant is scoped to, so revoking the tool
            revokes the path authority with it.
        subtree: A vault-relative directory prefix, or :data:`WHOLE_VAULT`.
            Stored normalized — forward slashes, no leading or trailing slash.
    """

    company_id: uuid.UUID
    agent_id: uuid.UUID
    tool_id: uuid.UUID
    subtree: str


def normalize_subtree(subtree: str) -> str:
    """Reduce a grant's subtree to the form paths are compared against.

    A grant is authored by an operator, so it is checked as strictly as a note
    path: a subtree that escapes the vault would authorize a path outside it.

    Args:
        subtree: A vault-relative directory, or :data:`WHOLE_VAULT`.

    Returns:
        The normalized subtree: forward slashes, no leading or trailing slash,
        or :data:`WHOLE_VAULT` unchanged.

    Raises:
        VaultBoundaryError: If the subtree is absolute, drive-relative, UNC, or
            walks above the vault root.
    """
    if subtree == WHOLE_VAULT:
        return WHOLE_VAULT

    text = subtree.strip().replace("\\", "/")
    if not text or text == "/":
        return WHOLE_VAULT

    from pathlib import PurePosixPath, PureWindowsPath

    # Checked against both flavours: a Windows drive or UNC prefix is not
    # absolute to PurePosixPath, and would otherwise pass as a relative name.
    if (
        text.startswith("/")
        or PurePosixPath(text).is_absolute()
        or PureWindowsPath(subtree).is_absolute()
        or PureWindowsPath(subtree).drive
    ):
        raise VaultBoundaryError(f"grant subtree must be vault-relative: {subtree!r}")

    parts: list[str] = []
    for part in text.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            # Refused rather than resolved: a grant that walks upward was either
            # authored wrongly or authored hostilely, and neither should silently
            # become a broader grant.
            raise VaultBoundaryError(f"grant subtree must not traverse upward: {subtree!r}")
        parts.append(part)

    return "/".join(parts) or WHOLE_VAULT


def canonical_vault_path(company_id: uuid.UUID, requested_path: str) -> str:
    """The vault-relative path a request actually names, after normalization.

    This is the only value authorization is allowed to reason about. It comes out
    of the §20 validator, so traversal, absolute paths, drive-relative paths, UNC
    paths, symlink escapes and disallowed extensions are already refused by the
    time a subtree comparison happens.

    Args:
        company_id: The company whose vault is addressed.
        requested_path: The path as supplied by the caller.

    Returns:
        The canonical vault-relative path, with forward slashes.

    Raises:
        VaultSecurityError: Whatever the validator refuses — boundary escape,
            disallowed extension, unconfigured vault.
    """
    resolved = resolve_note_path(company_id, requested_path)
    root = company_vault_root(company_id)
    # relative_to is safe here: resolve_note_path has already proven containment.
    return resolved.relative_to(root).as_posix()


class VaultWriteAuthorizer:
    """Decides whether an actor may write one vault path.

    Example:
        >>> authorizer = VaultWriteAuthorizer(registry)
        >>> authorizer.grant(company_id, agent_id, tool_id, "Projects")
        >>> authorizer.authorize(company_id, agent_id, tool_id, "Projects/Plan.md")
        'Projects/Plan.md'
    """

    def __init__(
        self,
        registry: object | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        """Bind authorizer to coarse tool access and persistent path grants."""
        self._registry = registry
        self._session_factory = session_factory

    async def grant_async(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        subtree: str,
        granted_by: str | None = None,
    ) -> VaultWriteGrant:
        """Persist one normalized subtree grant."""
        if self._session_factory is None:
            raise RuntimeError("database session factory is required")
        normalized = normalize_subtree(subtree)
        async with self._session_factory() as session:
            session.add(
                VaultWriteGrantRecord(
                    company_id=company_id,
                    agent_id=agent_id,
                    tool_id=tool_id,
                    subtree=normalized,
                    granted_by=granted_by,
                )
            )
            await session.commit()
        return VaultWriteGrant(company_id, agent_id, tool_id, normalized)

    async def revoke_async(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        subtree: str | None = None,
    ) -> None:
        """Revoke matching grants without deleting audit history."""
        if self._session_factory is None:
            raise RuntimeError("database session factory is required")
        conditions = [
            VaultWriteGrantRecord.company_id == company_id,
            VaultWriteGrantRecord.agent_id == agent_id,
            VaultWriteGrantRecord.tool_id == tool_id,
            VaultWriteGrantRecord.revoked_at.is_(None),
        ]
        if subtree is not None:
            conditions.append(VaultWriteGrantRecord.subtree == normalize_subtree(subtree))
        async with self._session_factory() as session:
            await session.execute(
                update(VaultWriteGrantRecord)
                .where(*conditions)
                .values(revoked_at=datetime.now(timezone.utc).replace(tzinfo=None))
            )
            await session.commit()

    async def subtrees_async(
        self, company_id: uuid.UUID, agent_id: uuid.UUID, tool_id: uuid.UUID
    ) -> frozenset[str]:
        """Load active subtrees from persistent state."""
        if self._session_factory is None:
            raise RuntimeError("database session factory is required")
        async with self._session_factory() as session:
            result = await session.execute(
                select(VaultWriteGrantRecord.subtree).where(
                    VaultWriteGrantRecord.company_id == company_id,
                    VaultWriteGrantRecord.agent_id == agent_id,
                    VaultWriteGrantRecord.tool_id == tool_id,
                    VaultWriteGrantRecord.revoked_at.is_(None),
                )
            )
            return frozenset(result.scalars().all())

    async def authorize_actor_async(
        self,
        company_id: uuid.UUID,
        actor: object,
        requested_path: str,
        tool_id: uuid.UUID | None = None,
    ) -> str:
        if not getattr(actor, "is_agent", False):
            return canonical_vault_path(company_id, requested_path)
        agent_id = getattr(actor, "agent_id", None)
        if agent_id is None or tool_id is None:
            raise VaultAuthorizationError("an agent write needs both an agent_id and a tool_id")
        return await self.authorize_async(company_id, agent_id, tool_id, requested_path)

    async def authorize_async(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        requested_path: str,
    ) -> str:
        """Authorize using fresh database state, safe for independent workers."""
        canonical = canonical_vault_path(company_id, requested_path)
        if self._registry is None:
            raise VaultAuthorizationError(f"agent {agent_id} has no access to tool {tool_id}")
        try:
            result = self._registry.has_access(company_id, agent_id, tool_id)
        except TypeError:
            result = self._registry.has_access(agent_id, tool_id)
        allowed = await result if hasattr(result, "__await__") else result
        if not allowed:
            raise VaultAuthorizationError(f"agent {agent_id} has no access to tool {tool_id}")
        granted = await self.subtrees_async(company_id, agent_id, tool_id)
        if not any(_covers(subtree, canonical) for subtree in granted):
            raise VaultAuthorizationError(
                f"agent {agent_id} is not authorized to write {canonical!r}"
            )
        return canonical

    def grant(self, company_id: uuid.UUID, agent_id: uuid.UUID, tool_id: uuid.UUID, subtree: str) -> VaultWriteGrant:
        """Legacy shape only; database callers must use ``grant_async``."""
        return VaultWriteGrant(company_id, agent_id, tool_id, normalize_subtree(subtree))

    def revoke(self, company_id: uuid.UUID, agent_id: uuid.UUID, tool_id: uuid.UUID, subtree: str | None = None) -> None:
        """Legacy no-op shape; database callers must use ``revoke_async``."""
        if subtree is not None:
            normalize_subtree(subtree)

    def subtrees(self, company_id: uuid.UUID, agent_id: uuid.UUID, tool_id: uuid.UUID) -> frozenset[str]:
        """Legacy shape with no authorization authority."""
        return frozenset()

    def authorize(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
        requested_path: str,
    ) -> str:
        """Authorize one write, returning the canonical path it applies to.

        The order matters. The path is canonicalized first, so every later
        decision is about the file that would actually be written; then the tool
        grant is checked; then the subtree. A refusal at any step is a refusal.

        Args:
            company_id: The company whose vault is addressed. Tenant isolation is
                structural — the path is derived from this id, so an agent cannot
                reach another company's note by naming it.
            agent_id: The agent attempting the write.
            tool_id: The write tool being used.
            requested_path: The path as supplied, before normalization.

        Returns:
            The canonical vault-relative path, ready to hand to a writer.

        Raises:
            VaultSecurityError: If the path itself is refused by the §20 validator
                — traversal, absolute, UNC, symlink escape, wrong extension.
            VaultAuthorizationError: If the agent holds no grant for the tool, or
                no grant covering the canonical path.
        """
        raise RuntimeError("synchronous authorization removed; use authorize_async")


    def authorize_actor(
        self,
        company_id: uuid.UUID,
        actor: object,
        requested_path: str,
        tool_id: uuid.UUID | None = None,
    ) -> str:
        """Authorize a write by any actor kind, returning the canonical path.

        An agent goes through the full chain. A system or operator actor does not:
        nobody granted it a tool, because no tool ran — the operator-invoked sync
        path of §17 is not an agent capability. It still gets the *path* half,
        because the §20 validator is about the filesystem boundary rather than
        about who is asking, and a system write outside the vault is as wrong as
        an agent's.

        Args:
            company_id: The company whose vault is addressed.
            actor: A :class:`~nexus.obsidian.actor.WriteActor`.
            requested_path: The path as supplied, before normalization.
            tool_id: The write tool, required for an agent actor.

        Returns:
            The canonical vault-relative path.

        Raises:
            VaultSecurityError: If the path is refused by the validator.
            VaultAuthorizationError: If an agent actor lacks tool access, a
                covering grant, or a ``tool_id``.
        """
        if not getattr(actor, "is_agent", False):
            return canonical_vault_path(company_id, requested_path)
        raise VaultAuthorizationError(
            "agent actor authorization requires async authorize_async"
        )


def _covers(subtree: str, canonical_path: str) -> bool:
    """Whether a normalized subtree contains a canonical vault-relative path.

    Compared segment-wise rather than by string prefix: ``Projects`` must not
    authorize ``ProjectsSecret/K.md``, which a ``startswith`` check would allow.

    Case sensitivity follows the filesystem, and on Windows that means
    ``projects/plan.md`` and ``Projects/Plan.md`` are one file. Comparing
    case-sensitively there would refuse a write the OS considers granted — the
    safe direction is to match what the filesystem will actually do, which
    ``resolve_note_path`` has already applied to the canonical form.
    """
    import os

    if subtree == WHOLE_VAULT:
        return True

    def parts(text: str) -> list[str]:
        segments = [segment for segment in text.split("/") if segment]
        # os.path.normcase folds case only where the platform does.
        return [os.path.normcase(segment) for segment in segments]

    subtree_parts = parts(subtree)
    path_parts = parts(canonical_path)
    # The path must live *under* the subtree, so it needs at least one more
    # segment (the filename) than the subtree has.
    return len(path_parts) > len(subtree_parts) and path_parts[: len(subtree_parts)] == subtree_parts


__all__ = [
    "WHOLE_VAULT",
    "VaultAuthorizationError",
    "VaultWriteAuthorizer",
    "VaultWriteGrant",
    "VaultSecurityError",
    "canonical_vault_path",
    "normalize_subtree",
]
