"""Memory evidence and governed trust: attach evidence, accept a candidate, assert, verify.

Every route is for a human company administrator (the Governance Studio write predicate,
``errors.can_write``, plus a database re-check of the active user and membership) and
answers 403 before it looks anything up. The company in the path is the caller's own or a
fixed 404; a memory or evidence id that is foreign and one that does not exist answer
alike. Mutations require ``Idempotency-Key`` and are replayable (see
``nexus.memory.evidence.run_once``); the generic idempotency middleware stands aside for
these paths. Bodies reject unknown fields, and nothing a caller sends can name a trust
level, grade, digest, company or actor. Responses and audit rows hold ids and states,
never memory, chat, tool or deliverable content.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict

from nexus.api.deps import CurrentPrincipal, DbSession
from nexus.api.routes.memory import MemoryCompanyId, principal_actor
from nexus.memory import evidence as ev
from nexus.memory.ingest import MemoryContext, MemoryOpError, http_error
from nexus.memory.lifecycle import accept_candidate, assert_trust, verify_trust
from nexus.services.governance_studio.errors import can_write

router = APIRouter(tags=["memory"])
_BASE = "/api/v1/companies/{company_id}/memory/{memory_id}"


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttachEvidence(_Body):
    evidence_kind: Literal["human_attestation", "chat_turn", "tool_invocation", "task_attempt"]
    source_id: uuid.UUID | None = None  # not for an attestation: the attester is the caller
    reason_code: str | None = None  # attestation only


class PromoteTrust(_Body):
    evidence_id: uuid.UUID


class NoBody(_Body):
    pass


class EvidenceOut(BaseModel):
    evidence_id: uuid.UUID
    memory_id: uuid.UUID
    evidence_kind: str
    source_type: str
    source_id: str
    reason_code: str | None
    grade: str
    policy_version: str
    created_by: str
    created_at: str


class EvidenceList(BaseModel):
    evidence: list[EvidenceOut]


class TransitionOut(BaseModel):
    memory_id: uuid.UUID
    status: str
    trust_state: str
    from_status: str | None = None
    from_trust_state: str | None = None
    evidence_id: uuid.UUID | None = None


async def _gate(db: Any, principal: Any) -> MemoryContext:
    """403 for anyone but a human company administrator, before any lookup."""
    ctx = MemoryContext(principal.company_id, principal_actor(principal))
    if not can_write(principal):
        raise MemoryOpError(
            "MEMORY_EVIDENCE_FORBIDDEN",
            "Only a human company administrator may manage memory evidence",
            403,
        )
    await ev.require_human_admin(db, ctx)
    return ctx


async def _mutate(
    db: Any,
    principal: Any,
    response: Response,
    idempotency_key: str | None,
    operation: str,
    memory_id: uuid.UUID,
    body: dict[str, Any],
    effect: Callable[[MemoryContext, str], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    try:
        ctx = await _gate(db, principal)
        key = ev.validate_key(idempotency_key)
        result, replayed = await ev.run_once(
            db, ctx, key=key, operation=operation, memory_id=memory_id,
            digest=ev.request_digest(operation, memory_id, ctx.actor, body),
            effect=lambda: effect(ctx, key),
        )
    except MemoryOpError as exc:
        raise http_error(exc) from exc
    if replayed:
        response.headers["Idempotency-Replayed"] = "true"
    return result


@router.post(
    f"{_BASE}/evidence", status_code=status.HTTP_201_CREATED, response_model=EvidenceOut
)
async def attach_memory_evidence(
    company_id: MemoryCompanyId,
    memory_id: uuid.UUID,
    body: AttachEvidence,
    response: Response,
    db: DbSession,
    principal: CurrentPrincipal,
    idempotency_key: str | None = Header(default=None, max_length=200),
) -> Any:
    """Attach evidence to an open memory. The server derives grade, digest and attester."""

    async def effect(ctx: MemoryContext, key: str) -> dict[str, Any]:
        return await ev.attach_evidence(
            db, ctx, memory_id,
            evidence_kind=body.evidence_kind,
            source_id=str(body.source_id) if body.source_id else None,
            reason_code=body.reason_code,
            idempotency_key=key,
        )

    return await _mutate(
        db, principal, response, idempotency_key, "attach_evidence", memory_id,
        body.model_dump(mode="json"), effect,
    )


@router.get(f"{_BASE}/evidence", response_model=EvidenceList)
async def list_memory_evidence(
    company_id: MemoryCompanyId, memory_id: uuid.UUID, db: DbSession, principal: CurrentPrincipal
) -> Any:
    """The evidence of one memory, oldest first. Audited as ``memory.evidence_reviewed``."""
    try:
        ctx = await _gate(db, principal)
        return {"evidence": await ev.list_evidence(db, ctx, memory_id)}
    except MemoryOpError as exc:
        raise http_error(exc) from exc


@router.post(f"{_BASE}/accept", response_model=TransitionOut)
async def accept_memory_candidate(
    company_id: MemoryCompanyId,
    memory_id: uuid.UUID,
    response: Response,
    db: DbSession,
    principal: CurrentPrincipal,
    body: NoBody | None = None,
    idempotency_key: str | None = Header(default=None, max_length=200),
) -> Any:
    """candidate -> active. Makes the memory eligible for prompts; trust stays as it was."""

    async def effect(ctx: MemoryContext, key: str) -> dict[str, Any]:
        row = await accept_candidate(db, ctx, memory_id, idempotency_key=key)
        return {
            "memory_id": str(row.id), "status": row.status, "trust_state": row.trust_state,
            "from_status": "candidate",
        }

    return await _mutate(
        db, principal, response, idempotency_key, "accept_candidate", memory_id, {}, effect
    )


def _trust_route(
    path: str, operation: str, step: Callable[..., Awaitable[Any]], frm: str, doc: str
):
    @router.post(f"{_BASE}/trust/{path}", response_model=TransitionOut, name=operation)
    async def promote(
        company_id: MemoryCompanyId,
        memory_id: uuid.UUID,
        body: PromoteTrust,
        response: Response,
        db: DbSession,
        principal: CurrentPrincipal,
        idempotency_key: str | None = Header(default=None, max_length=200),
    ) -> Any:
        async def effect(ctx: MemoryContext, key: str) -> dict[str, Any]:
            row = await step(db, ctx, memory_id, body.evidence_id, idempotency_key=key)
            return {
                "memory_id": str(row.id), "status": row.status, "trust_state": row.trust_state,
                "from_trust_state": frm, "evidence_id": str(body.evidence_id),
            }

        return await _mutate(
            db, principal, response, idempotency_key, operation, memory_id,
            body.model_dump(mode="json"), effect,
        )

    promote.__doc__ = doc
    return promote


assert_memory_trust = _trust_route(
    "assert", "assert_trust", assert_trust, "untrusted",
    "untrusted -> asserted on an active memory, backed by evidence graded assert or verify.",
)
verify_memory_trust = _trust_route(
    "verify", "verify_trust", verify_trust, "asserted",
    "asserted -> verified on an active memory, backed by evidence graded verify.",
)
