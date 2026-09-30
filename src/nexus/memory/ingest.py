"""The one path that creates ``memory_records`` rows.

Every writer (chat extraction, the memory API, executive memory, layered L2/L3,
seeding, ``MemoryStore``) calls :func:`ingest_memory`. It derives nothing from the
caller that the server owns: company and actor come from a :class:`MemoryContext`
built from the authenticated principal, and status and trust come from the
:class:`Origin`, never from a request field.

Idempotency is per source event, not per text. ``ingestion_key`` hashes company,
source, extractor, item key and the normalized redacted content, and is unique per
company, so a retry of the same event returns the existing row while the same words
from another source stay a separate row. No LLM call, no file write, and no
transaction held across outside work happen here; the caller owns the commit.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from nexus.memory.safety import (
    MAX_STRING,
    UNTRUSTED,
    MemoryRejected,
    reserved_keys_in,
    sanitize_metadata,
    sanitize_text,
    sanitize_value,
)
from nexus.models.memory import MEMORY_TYPES, MemoryRecord

_SCOPE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
_SOURCE_ID = re.compile(r"^[A-Za-z0-9._:@/+=-]{1,128}$")
# Source kinds that name a row in this database; anything else is a label plus a free id.
_ENTITY_SOURCES = ("chat_message", "chat_turn", "memory_record")
SOURCE_TYPES = frozenset(
    {"chat_message", "chat_turn", "chat_reply", "memory_record", "api_request", "seed",
     "system", "cold_archive"}
)


class MemoryOpError(Exception):
    """A refused memory operation.

    ``code`` and ``status_code`` are stable; the text never echoes content.
    """

    def __init__(self, code: str, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def http_error(exc: MemoryOpError | MemoryRejected) -> Any:
    """The HTTPException for a refusal, in the ``{code, message}`` shape the API already uses."""
    from fastapi import HTTPException

    status = exc.status_code if isinstance(exc, MemoryOpError) else 422
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


class Origin(StrEnum):
    """Who is writing. The value is also the legacy ``origin`` metadata label."""

    API = "api"  # a person or service through the public API
    HUMAN = "human"  # a CEO directive typed by a person
    TOOL = "tool"  # an agent's tool call (executive memory)
    CHAT_EXTRACTION = "chat_extraction"  # a fact pulled from model output
    SEED = "seed"  # platform-authored import
    PROMOTION = "promotion"  # a copy of an existing row; inherits its state
    SYSTEM = "system"  # server code with no better provenance


# (status, trust_state). Agents can never write "verified"; that waits for Phase 3.
_POLICY = {
    Origin.API: ("active", "asserted"),
    Origin.HUMAN: ("active", "asserted"),
    Origin.TOOL: ("active", "untrusted"),
    Origin.CHAT_EXTRACTION: ("candidate", "untrusted"),
    Origin.SEED: ("active", "asserted"),
    Origin.SYSTEM: ("active", "untrusted"),
}


@dataclass(frozen=True)
class MemoryContext:
    """Server-derived identity of a write. Never built from request fields."""

    company_id: uuid.UUID
    actor: str  # user:<id>, agent:<id>, run:<id>, service:<id>, policy:<name>


@dataclass
class MemoryInput:
    """What a caller may say about a memory. Identity, trust, hash and lifecycle are not here."""

    scope: str
    content: str
    memory_type: str = "unknown"
    agent_id: uuid.UUID | None = None
    scope_id: uuid.UUID | None = None
    importance: float = 0.5
    tier: str = "warm"
    metadata: dict[str, Any] | None = None  # caller data; reserved keys are refused
    source_type: str | None = None
    source_id: str | None = None
    source_created_at: datetime | None = None
    extractor_version: str | None = None
    item_key: str = ""  # fact ordinal or another stable key within one source event
    content_max: int = MAX_STRING
    # Server-only, set by lifecycle / trusted internal callers, never by a request:
    server_metadata: dict[str, Any] = field(default_factory=dict)
    supersedes_id: uuid.UUID | None = None
    record_id: uuid.UUID | None = None
    access_count: int = 0


@dataclass(frozen=True)
class IngestResult:
    record: MemoryRecord
    created: bool


def normalize_content(text: str) -> str:
    """NFC, LF line ends, no trailing blanks per line, no outer whitespace. Deterministic."""
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def derive_ingestion_key(
    company_id: uuid.UUID, item: MemoryInput, source_id: str, digest: str
) -> str:
    """SHA-256 over every field that makes one source event distinct."""
    binding = json.dumps(
        [item.scope, str(item.agent_id or ""), str(item.scope_id or ""), item.memory_type],
        separators=(",", ":"),
    )
    parts = [
        str(company_id), item.source_type or "", source_id, item.extractor_version or "",
        item.item_key, digest, hashlib.sha256(binding.encode()).hexdigest(),
    ]
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


def executive_source(source: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Source kind and id for executive metadata; only a real message or turn id counts."""
    for key, kind in (("message_id", "chat_message"), ("turn_id", "chat_turn")):
        if source and source.get(key):
            return kind, str(source[key])
    return None, None


def _now() -> datetime:
    from nexus.models._time import utcnow

    return utcnow()


async def get_in_company(
    db: Any, company_id: uuid.UUID, memory_id: uuid.UUID
) -> MemoryRecord | None:
    return (
        await db.execute(
            select(MemoryRecord)
            .where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _validate_refs(db: Any, ctx: MemoryContext, item: MemoryInput) -> None:
    """Scope, ownership and source references, all inside the caller's company."""
    if not _SCOPE.match(item.scope or ""):
        raise MemoryOpError("MEMORY_SCOPE_INVALID", "Memory scope is not valid")
    if item.memory_type not in MEMORY_TYPES:
        raise MemoryOpError("MEMORY_TYPE_INVALID", "Memory type is not valid")
    if item.agent_id is not None:
        from nexus.models.agent import Agent

        found = await db.execute(
            select(Agent.id).where(Agent.id == item.agent_id, Agent.company_id == ctx.company_id)
        )
        if found.first() is None:
            raise MemoryOpError("MEMORY_AGENT_NOT_FOUND", "Agent not found", 404)
    if item.scope_id is not None and item.scope_id not in (item.agent_id, ctx.company_id):
        await _validate_scope_owner(db, ctx, item)
    if item.supersedes_id is not None:
        older = await get_in_company(db, ctx.company_id, item.supersedes_id)
        if older is None:
            raise MemoryOpError("MEMORY_NOT_FOUND", "Memory not found", 404)

    if item.source_type is not None and item.source_type not in SOURCE_TYPES:
        raise MemoryOpError("MEMORY_SOURCE_INVALID", "Memory source is not valid")
    if item.source_id is not None and not _SOURCE_ID.match(item.source_id):
        raise MemoryOpError("MEMORY_SOURCE_INVALID", "Memory source id is not valid")
    if item.source_type in _ENTITY_SOURCES:
        await _validate_entity_source(db, ctx, item)


async def _validate_scope_owner(db: Any, ctx: MemoryContext, item: MemoryInput) -> None:
    """An agent, team or department scope id must belong to the company.

    Other scopes take only agent/company.
    """
    from nexus.models.agent import Agent
    from nexus.models.company import Department, Team

    model = {"agent": Agent, "team": Team, "department": Department}.get(item.scope)
    if model is not None:
        found = await db.execute(
            select(model.id).where(model.id == item.scope_id, model.company_id == ctx.company_id)
        )
        if found.first() is not None:
            return
    raise MemoryOpError("MEMORY_SCOPE_MISMATCH", "scope_id does not belong to this company")


async def _validate_entity_source(db: Any, ctx: MemoryContext, item: MemoryInput) -> None:
    try:
        ref = uuid.UUID(item.source_id or "")
    except ValueError:
        raise MemoryOpError("MEMORY_SOURCE_INVALID", "Memory source id is not valid") from None
    if item.source_type == "memory_record":
        found = await get_in_company(db, ctx.company_id, ref)
    elif item.source_type == "chat_message":
        from nexus.models.chat import ChatMessage

        found = (
            await db.execute(
                select(ChatMessage.id).where(
                    ChatMessage.id == ref, ChatMessage.company_id == ctx.company_id
                )
            )
        ).first()
    else:
        from nexus.models.chat_turn import ChatTurn

        found = (
            await db.execute(
                select(ChatTurn.id).where(
                    ChatTurn.id == ref, ChatTurn.company_id == ctx.company_id
                )
            )
        ).first()
    if found is None:
        raise MemoryOpError("MEMORY_SOURCE_INVALID", "Memory source not found in this company")


def _existing_by_key(company_id: uuid.UUID, key: str):
    return (
        select(MemoryRecord)
        .where(MemoryRecord.company_id == company_id, MemoryRecord.ingestion_key == key)
        .execution_options(populate_existing=True)
    )


async def _conflicting_event(
    db: Any, ctx: MemoryContext, item: MemoryInput, source_id: str, key: str
) -> None:
    """Same source event (an Idempotency-Key) already stored with a different payload -> 409."""
    other = (
        await db.execute(
            select(MemoryRecord.ingestion_key).where(
                MemoryRecord.company_id == ctx.company_id,
                MemoryRecord.source_type == item.source_type,
                MemoryRecord.source_id == source_id,
                MemoryRecord.extractor_version == item.extractor_version,
            )
        )
    ).scalars().first()
    if other is not None and other != key:
        raise MemoryOpError(
            "MEMORY_IDEMPOTENCY_CONFLICT",
            "This idempotency key was already used with a different request",
            409,
        )


async def begin_write(db: Any) -> None:
    """Start the write transaction before reading, on SQLite.

    SQLite's driver opens its transaction at the first write, so a memory write that
    starts with a read and a SAVEPOINT runs the SAVEPOINT as the outermost
    transaction: releasing it commits the row before the caller's later work (the
    audit row), and a writer that commits in between makes the audit insert fail
    at once with "database is locked". A statement that changes no row takes the
    write lock up front. PostgreSQL needs nothing.
    """
    try:
        dialect = db.get_bind().dialect.name
    except Exception:  # noqa: BLE001 - a test double or unbound session: nothing to do
        return
    if dialect == "sqlite":
        await db.execute(text("UPDATE memory_records SET id = id WHERE 0"))


async def ingest_memory(
    db: Any,
    ctx: MemoryContext,
    item: MemoryInput,
    origin: Origin,
    *,
    parent: MemoryRecord | None = None,
    payload_conflict_409: bool = False,
) -> IngestResult:
    """Validate, sanitize and append one memory. Flushes; the caller commits.

    ``parent`` is only for :attr:`Origin.PROMOTION`: the copy takes the parent's
    status and trust and points its source at the parent. ``payload_conflict_409``
    is for a caller-supplied idempotency key: the same source event with different
    content is a conflict rather than a second row.

    Raises:
        MemoryRejected: content or metadata failed the safety bounds.
        MemoryOpError: scope, agent or source refused, or an idempotency conflict.
    """
    await begin_write(db)
    # 1-3. Tenant and actor come from ``ctx``; validate scope, ownership and source.
    if origin is Origin.PROMOTION:
        if parent is None or parent.company_id != ctx.company_id:
            raise MemoryOpError("MEMORY_SOURCE_INVALID", "Promotion needs a parent in this company")
        status, trust_state = parent.status, parent.trust_state
        item.source_type, item.source_id = "memory_record", str(parent.id)
    else:
        status, trust_state = _POLICY[origin]
    if item.source_id is None:
        # No real source instance: the server mints an event id, so unrelated writes never collapse.
        item.source_type = item.source_type or "system"
        item.source_id = f"evt:{uuid.uuid4()}"
    await _validate_refs(db, ctx, item)

    # 4-5. Redact recursively, then normalize deterministically.
    text, hit = sanitize_text(item.content, max_len=item.content_max)
    text = normalize_content(text)
    if not text:
        raise MemoryOpError("MEMORY_EMPTY", "Memory content is empty")
    user_meta, meta_hit = sanitize_metadata(item.metadata)
    server_meta, server_hit = sanitize_metadata(item.server_metadata, allow_reserved=True)
    redacted = hit or meta_hit or server_hit

    # 6-7. Hash and derive the ingestion key.
    digest = content_hash(text)
    key = derive_ingestion_key(ctx.company_id, item, item.source_id, digest)

    existing = (await db.execute(_existing_by_key(ctx.company_id, key))).scalar_one_or_none()
    if existing is not None:
        return IngestResult(existing, False)
    if payload_conflict_409:
        await _conflicting_event(db, ctx, item, item.source_id, key)

    metadata: dict[str, Any] = {
        **user_meta,
        **server_meta,
        "origin": origin.value,
        "recorded_by": ctx.actor,
        "redacted": redacted,
    }
    if origin is Origin.CHAT_EXTRACTION:
        metadata["trust"] = UNTRUSTED
        # Legacy readers look for {"source": {"type": ...}}; the columns are the record of truth.
        metadata.setdefault("source", {"type": item.source_type})
    elif origin is Origin.API:
        metadata["trust"] = "operator_supplied"
    elif parent is not None:
        # A promoted copy reads like its parent to anything that labels by origin or trust.
        inherited = parent.record_metadata or {}
        metadata["origin"] = inherited.get("origin", origin.value)
        if "trust" in inherited:
            metadata["trust"] = inherited["trust"]
        metadata["promoted_from"] = str(parent.id)
    kwargs: dict[str, Any] = {"id": item.record_id} if item.record_id else {}
    record = MemoryRecord(
        **kwargs,
        company_id=ctx.company_id,
        agent_id=item.agent_id,
        scope=item.scope,
        scope_id=item.scope_id,
        content=text,
        record_metadata=metadata,
        importance=item.importance,
        access_count=item.access_count,
        tier=item.tier,
        memory_type=item.memory_type,
        status=status,
        trust_state=trust_state,
        source_type=item.source_type,
        source_id=item.source_id,
        source_created_at=item.source_created_at,
        extractor_version=item.extractor_version,
        content_hash=digest,
        ingestion_key=key,
        supersedes_id=item.supersedes_id,
    )

    # 8-9. Append; a concurrent identical event loses the unique race and reads the winner.
    try:
        async with db.begin_nested():
            db.add(record)
            await db.flush()
    except IntegrityError:
        winner = (await db.execute(_existing_by_key(ctx.company_id, key))).scalar_one_or_none()
        if winner is None:
            raise
        return IngestResult(winner, False)

    # 10. Audit safe metadata only: never the content itself.
    from nexus.services import manager_service as ms

    await ms.audit(
        db, ctx.company_id, "memory.recorded", ctx.actor, "memory", record.id,
        scope=item.scope, agent_id=item.agent_id, memory_type=item.memory_type,
        status=status, trust_state=trust_state, source_type=item.source_type,
        content_hash=digest, length=len(text), redacted=redacted,
    )
    return IngestResult(record, True)


def clean_user_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """``metadata`` without server-owned keys, for carrying an old row's data onto a successor."""
    drop = set(reserved_keys_in(metadata))
    clean, _ = sanitize_value({k: v for k, v in (metadata or {}).items() if k not in drop})
    return clean
