"""Governed agent capability for replacing one existing Obsidian note."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.obsidian import (
    ObsidianWriteError,
    ObsidianWriter,
    VaultAuthorizationError,
    VaultSecurityError,
    WriteActor,
    WriteApprovalError,
    WriteConflictError,
    WriteContentError,
    WriteRecoveryError,
    VaultWriteAuthorizer,
    safe_reason,
)
from nexus.tools.registry import ToolDefinition, ToolRegistry

OBSIDIAN_NOTE_REPLACE_NAME = "obsidian.note_replace"
_OBSIDIAN_TOOL_NAMESPACE = uuid.UUID("2bb7ed7f-6dd6-5f41-a4f4-59c6bd1c4694")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

OBSIDIAN_NOTE_REPLACE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "vault_path": {
            "type": "string",
            "description": "Vault-relative path of an existing Markdown note.",
        },
        "content": {
            "type": "string",
            "description": "Replacement UTF-8 Markdown content.",
        },
        "expected_hash": {
            "type": "string",
            "pattern": "^[0-9a-f]{64}$",
            "description": "SHA-256 hash of the current note bytes.",
        },
        "approval_id": {
            "type": "string",
            "format": "uuid",
            "description": "Approved obsidian_write request bound to this exact mutation.",
        },
    },
    "required": ["vault_path", "content", "expected_hash", "approval_id"],
}


def obsidian_note_replace_tool_id(company_id: uuid.UUID) -> uuid.UUID:
    """Return stable, company-bound identity for the one Obsidian write tool."""
    return uuid.uuid5(_OBSIDIAN_TOOL_NAMESPACE, str(company_id))


def register_obsidian_note_replace(
    registry: ToolRegistry, company_id: uuid.UUID
) -> ToolDefinition:
    """Register the governed capability in the existing local ToolRegistry.

    The returned ID is also the ID that must be persisted in ``Tool`` and used
    for ``ToolAccess``. Registration grants no access by itself.
    """
    return registry.register_tool(
        ToolDefinition(
            id=obsidian_note_replace_tool_id(company_id),
            company_id=company_id,
            name=OBSIDIAN_NOTE_REPLACE_NAME,
            description=(
                "Replace content of one existing Markdown note after ToolAccess, "
                "subtree authorization, approval, conflict, and secret checks."
            ),
            tool_type="function",
            parameters=OBSIDIAN_NOTE_REPLACE_SCHEMA,
            risk_level="high",
            tags=["obsidian", "write", "note_replace"],
        )
    )


class ObsidianToolExecutionError(RuntimeError):
    """Structured governed-tool failure surfaced as executor failure."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        super().__init__(result.get("reason", "tool execution failed"))


@dataclass(frozen=True)
class ObsidianNoteReplaceResult:
    """Client-safe result for one governed note replacement."""

    status: str
    vault_path: str | None = None
    previous_hash: str | None = None
    content_hash: str | None = None
    size_bytes: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status}
        for key in (
            "vault_path",
            "previous_hash",
            "content_hash",
            "size_bytes",
            "reason",
        ):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


class ObsidianNoteReplaceTool:
    """Bind one governed operation to request-scoped company and agent identity."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        registry: ToolRegistry,
        session_factory: async_sessionmaker[AsyncSession],
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        tool_id: uuid.UUID,
    ) -> None:
        expected_tool_id = obsidian_note_replace_tool_id(company_id)
        if tool_id != expected_tool_id:
            raise ValueError("tool identity is not valid for company")
        self._db = db
        self._registry = registry
        self._session_factory = session_factory
        self._company_id = company_id
        self._agent_id = agent_id
        self._tool_id = tool_id

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute only existing-note replacement through ``ObsidianWriter``."""
        try:
            requested_path, content, expected_hash, approval_id = self._arguments(arguments)
            authorizer = VaultWriteAuthorizer(self._registry, self._session_factory)
            result = await ObsidianWriter(
                self._db,
                authorizer=authorizer,
                approval_required=True,
            ).replace_note(
                self._company_id,
                requested_path,
                content,
                WriteActor.agent(self._agent_id),
                tool_id=self._tool_id,
                expected_hash=expected_hash,
                approval_id=approval_id,
            )
            return ObsidianNoteReplaceResult(
                status="updated",
                vault_path=result.vault_path,
                previous_hash=result.previous_hash,
                content_hash=result.content_hash,
                size_bytes=result.size_bytes,
            ).as_dict()
        except Exception as exc:  # noqa: BLE001 - map all tool output safely
            failure = self._failure(exc)
            raise ObsidianToolExecutionError(failure) from exc

    @staticmethod
    def _arguments(
        arguments: dict[str, Any],
    ) -> tuple[str, str, str, uuid.UUID | None]:
        if not isinstance(arguments, dict):
            raise ValueError("arguments must be an object")
        allowed = {"vault_path", "content", "expected_hash", "approval_id"}
        if set(arguments) - allowed:
            raise ValueError("unsupported note replacement argument")
        requested_path = arguments.get("vault_path")
        content = arguments.get("content")
        expected_hash = arguments.get("expected_hash")
        approval_raw = arguments.get("approval_id")
        if not isinstance(requested_path, str) or not requested_path:
            raise ValueError("vault_path is required")
        if not isinstance(content, str):
            raise ValueError("content must be text")
        if not isinstance(expected_hash, str) or not _SHA256.fullmatch(expected_hash):
            raise ValueError("expected_hash must be a lowercase SHA-256 hash")
        if approval_raw is None:
            approval_id = None
        else:
            try:
                approval_id = uuid.UUID(str(approval_raw))
            except (ValueError, TypeError, AttributeError) as exc:
                raise ValueError("approval_id must be a UUID") from exc
        return requested_path, content, expected_hash, approval_id

    @staticmethod
    def _failure(exc: Exception) -> dict[str, Any]:
        if isinstance(exc, WriteConflictError):
            status = "conflict"
            reason = "note changed since expected_hash"
        elif isinstance(exc, VaultAuthorizationError):
            status = "denied"
            reason = "agent lacks note write authorization"
        elif isinstance(exc, WriteApprovalError):
            status = "approval_failure"
            reason = "approval missing, expired, or not bound to requested write"
        elif isinstance(exc, WriteRecoveryError):
            status = "recovery_failure"
            reason = "write recovery failed safely"
        elif isinstance(exc, WriteContentError):
            status = "secret_rejection" if "secret" in str(exc).lower() else "invalid_content"
            reason = "replacement content refused"
        elif isinstance(exc, VaultSecurityError):
            status = "invalid_path"
            reason = safe_reason(exc)
        elif isinstance(exc, FileNotFoundError):
            status = "invalid_path"
            reason = "existing note not found"
        elif isinstance(exc, ObsidianWriteError):
            message = str(exc).lower()
            status = "audit_failure" if "audit" in message else "internal_execution_failure"
            reason = "write persistence failed"
        else:
            status = "internal_execution_failure"
            reason = "tool execution failed"
        return ObsidianNoteReplaceResult(status=status, reason=reason).as_dict()


__all__ = [
    "OBSIDIAN_NOTE_REPLACE_NAME",
    "OBSIDIAN_NOTE_REPLACE_SCHEMA",
    "ObsidianNoteReplaceResult",
    "ObsidianToolExecutionError",
    "ObsidianNoteReplaceTool",
    "obsidian_note_replace_tool_id",
    "register_obsidian_note_replace",
]
