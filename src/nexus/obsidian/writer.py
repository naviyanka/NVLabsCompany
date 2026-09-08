"""Controlled Obsidian note replacement (ADR 0002 §20 controls 7–13).

This is deliberately one operation: replace an existing Markdown note. It does
not create, delete, move, merge, or commit Git changes.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.governance.audit_service import record_audit
from nexus.models.obsidian import ObsidianDocument
from nexus.obsidian.actor import WriteActor
from nexus.obsidian.authorization import VaultWriteAuthorizer
from nexus.obsidian.frontmatter import parse_note
from nexus.obsidian.secret_scan import SecretScanResult, scan_bytes
import nexus.obsidian.security as obsidian_security
from nexus.obsidian.security import resolve_note_path
from nexus.obsidian.wikilinks import note_links

class ObsidianWriteError(Exception):
    """Base error for a refused or failed vault write."""


class WriteConflictError(ObsidianWriteError):
    """The note changed after NEXUS indexed it."""


class WriteApprovalError(ObsidianWriteError):
    """The requested write has no usable approval."""


class WriteContentError(ObsidianWriteError):
    """The proposed content cannot be written safely."""


class WriteRecoveryError(ObsidianWriteError):
    """Filesystem/DB failure could not be reconciled safely."""


@dataclass(frozen=True)
class WriteResult:
    """Outcome of one atomic note replacement."""

    vault_path: str
    content_hash: str
    previous_hash: str
    size_bytes: int
    scan: SecretScanResult


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _naive_utc(timestamp: float) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None)


class ObsidianWriter:
    """Replace an existing note after every writeback gate passes."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        authorizer: VaultWriteAuthorizer | None = None,
        approval_required: bool = True,
    ) -> None:
        self._db = db
        self._authorizer = authorizer
        self._approval_required = approval_required
        self._write_lock = asyncio.Lock()

    async def replace_note(
        self,
        company_id: uuid.UUID,
        requested_path: str,
        content: str | bytes,
        actor: WriteActor,
        *,
        tool_id: uuid.UUID | None = None,
        expected_hash: str | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> WriteResult:
        async with self._write_lock:
            return await self._replace_note(
                company_id,
                requested_path,
                content,
                actor,
                tool_id=tool_id,
                expected_hash=expected_hash,
                approval_id=approval_id,
            )

    async def _replace_note(
        self,
        company_id: uuid.UUID,
        requested_path: str,
        content: str | bytes,
        actor: WriteActor,
        *,
        tool_id: uuid.UUID | None = None,
        expected_hash: str | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> WriteResult:
        """Atomically replace one existing note.

        All refusal checks happen before the first filesystem mutation. This method
        owns the registry transaction and commits the document and audit together.
        If commit fails after replacement, it restores the previous bytes when the
        target still contains this write.
        """
        if self._authorizer is None:
            raise WriteContentError("write authorization is required")
        if not isinstance(content, (str, bytes)):
            raise WriteContentError("note content must be text or UTF-8 bytes")
        data = content.encode("utf-8") if isinstance(content, str) else content
        limit = obsidian_security.settings.obsidian_max_note_bytes
        if len(data) > limit:
            raise WriteContentError(f"note is {len(data)} bytes, over the {limit}-byte limit")
        scan = scan_bytes(data)
        if not scan.allowed:
            raise WriteContentError(scan.detail or "secret scan refused the write")

        canonical = await self._authorizer.authorize_actor_async(
            company_id, actor, requested_path, tool_id
        )
        path = resolve_note_path(company_id, canonical)
        if not path.is_file():
            raise FileNotFoundError(canonical)
        try:
            previous_data = path.read_bytes()
            current = previous_data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError as exc:
            raise WriteContentError("existing note is not valid UTF-8") from exc
        previous_hash = _hash_text(current)

        row = (
            await self._db.execute(
                select(ObsidianDocument).where(
                    ObsidianDocument.company_id == company_id,
                    ObsidianDocument.vault_path == canonical,
                )
            )
        ).scalar_one_or_none()
        indexed_hash = row.content_hash if row is not None else None
        if indexed_hash is not None and previous_hash != indexed_hash:
            raise WriteConflictError(f"note changed outside NEXUS: {canonical}")
        if expected_hash is not None and previous_hash != expected_hash:
            raise WriteConflictError(f"note hash does not match expected value: {canonical}")
        new_text = data.decode("utf-8")
        new_hash = _hash_text(new_text)
        if self._approval_required and approval_id is None:
            raise WriteApprovalError("approval is required for this write")
        if approval_id is not None:
            await self._check_approval(
                approval_id, company_id, actor, canonical, previous_hash, new_hash, tool_id
            )

        self._atomic_replace(path, data)
        stat = path.stat()
        parsed = parse_note(new_text)
        try:
            if row is None:
                row = ObsidianDocument(
                    company_id=company_id,
                    vault_path=canonical,
                    content_hash=new_hash,
                    mtime=_naive_utc(stat.st_mtime),
                    doc_type=parsed.doc_type,
                    title=parsed.title,
                    wikilink_targets=list(note_links(parsed.metadata, parsed.body)),
                    index_status="stale",
                )
                self._db.add(row)
            else:
                row.content_hash = new_hash
                row.mtime = _naive_utc(stat.st_mtime)
                row.doc_type = parsed.doc_type
                row.title = parsed.title
                row.wikilink_targets = list(note_links(parsed.metadata, parsed.body))
                row.index_status = "stale"
                row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
            await self._db.flush()
            await record_audit(
                company_id,
                "obsidian.note_replaced",
                actor_type=actor.kind,
                actor_id=(
                    str(actor.agent_id or actor.user_id)
                    if actor.agent_id is not None or actor.user_id is not None
                    else None
                ),
                resource_type="obsidian_note",
                resource_id=canonical,
                details={
                    **actor.audit_fields(),
                    "tool_id": str(tool_id) if tool_id is not None else None,
                    "approval_id": str(approval_id) if approval_id is not None else None,
                    "previous_hash": previous_hash,
                    "content_hash": new_hash,
                    "size_bytes": len(data),
                },
                db=self._db,
                raise_on_error=True,
            )
            await self._db.commit()
        except Exception as exc:
            try:
                if _hash_text(path.read_text(encoding="utf-8")) != new_hash:
                    raise WriteRecoveryError(
                        "database/index persistence failed; note changed before recovery"
                    )
                self._atomic_replace(path, previous_data)
            except WriteRecoveryError:
                raise
            except Exception as recovery_exc:
                raise WriteRecoveryError(
                    "database/index persistence failed; filesystem recovery failed"
                ) from recovery_exc
            message = (
                "audit persistence failed; filesystem restored"
                if "audit log write failed" in str(exc) or "down" in str(exc)
                else "database/index persistence failed; filesystem restored"
            )
            raise ObsidianWriteError(message) from exc
        return WriteResult(canonical, new_hash, previous_hash, len(data), scan)

    async def write_note(self, *args: Any, **kwargs: Any) -> WriteResult:
        """Compatibility alias for :meth:`replace_note`."""
        return await self.replace_note(*args, **kwargs)

    async def _check_approval(
        self,
        approval_id: uuid.UUID,
        company_id: uuid.UUID,
        actor: WriteActor,
        canonical: str,
        previous_hash: str,
        new_hash: str,
        tool_id: uuid.UUID | None,
    ) -> None:
        from nexus.models.governance import Approval

        approval = (
            await self._db.execute(select(Approval).where(Approval.id == approval_id))
        ).scalar_one_or_none()
        if (
            approval is None
            or approval.company_id != company_id
            or approval.status != "approved"
            or approval.type != "obsidian_write"
            or approval.expires_at is not None
            and approval.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)
        ):
            raise WriteApprovalError("approval is missing, unapproved, expired, or mismatched")
        if actor.is_agent and approval.requested_by_agent_id != actor.agent_id:
            raise WriteApprovalError("approval belongs to another agent")
        payload = approval.payload or {}
        if (
            payload.get("vault_path") != canonical
            or payload.get("previous_hash") != previous_hash
            or payload.get("content_hash") != new_hash
            or payload.get("tool_id") != str(tool_id)
        ):
            raise WriteApprovalError("approval does not match requested write")

    @staticmethod
    def _atomic_replace(path: Path, data: bytes) -> None:
        """Write beside target, fsync, then replace; clean temp on failure."""
        fd, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


__all__ = [
    "ObsidianWriter",
    "ObsidianWriteError",
    "WriteApprovalError",
    "WriteConflictError",
    "WriteContentError",
    "WriteRecoveryError",
    "WriteResult",
]
