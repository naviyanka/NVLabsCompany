"""Approval API endpoints - governance approval workflows."""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.governance.approval_signing import SignatureError
from nexus.models.governance import Approval
from nexus.services.approval_service import ApprovalService

router = APIRouter(tags=["approvals"])


class ApprovalCreate(BaseModel):
    """Request body for creating an approval request."""

    type: str
    requested_by_agent_id: uuid.UUID
    payload: dict[str, Any] | None = None
    expires_at: datetime | None = None


class ApprovalDecision(BaseModel):
    """Request body for approving or rejecting."""

    decided_by: str
    decision_note: str | None = None


class ApprovalSignatureCreate(BaseModel):
    """Request body for signing an approval."""

    subject: str
    signature: str


class ApprovalResponse(BaseModel):
    """Response model for an approval."""

    id: uuid.UUID
    company_id: uuid.UUID
    type: str
    requested_by_agent_id: uuid.UUID | None = None
    status: str
    payload: dict[str, Any] | None = None
    decision_note: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    # So a client knows a request is quorum-gated before it tries to approve it.
    required_signatures: int = 1
    created_at: datetime
    updated_at: datetime


@router.post(
    "/api/v1/companies/{company_id}/approvals",
    status_code=status.HTTP_201_CREATED,
    response_model=ApprovalResponse,
)
async def create_approval(
    company_id: uuid.UUID, body: ApprovalCreate, db: DbSession
) -> Any:
    """Create a new approval request through the single approval service."""
    return await ApprovalService(db).request_approval(
        company_id=company_id,
        approval_type=body.type,
        requested_by_agent_id=body.requested_by_agent_id,
        payload=body.payload,
        expires_at=body.expires_at,
    )


@router.get(
    "/api/v1/companies/{company_id}/approvals/pending",
    response_model=list[ApprovalResponse],
)
async def list_pending_approvals(
    company_id: uuid.UUID,
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List pending approvals for a company."""
    stmt = (
        select(Approval)
        .where(
            Approval.company_id == company_id,
            Approval.status == "pending",
        )
        .offset(offset)
        .limit(limit)
        .order_by(Approval.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/approvals/{approval_id}/approve",
    response_model=ApprovalResponse,
)
async def approve(
    approval_id: uuid.UUID, body: ApprovalDecision, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Approve a pending approval request.

    A high-risk request carries ``required_signatures > 1`` and is refused with
    409 until that many distinct parties have signed it. Flipping the status is
    what an attacker with one operator's session can do; producing a signature
    needs a private key the platform never holds.
    """
    existing = await db.execute(
        select(Approval).where(Approval.id == approval_id, Approval.company_id == company_id)
    )
    if existing.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found or not pending",
        )
    try:
        approval = await ApprovalService(db).approve(
            approval_id, body.decided_by, body.decision_note
        )
    except SignatureError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found or not pending",
        )
    return approval


@router.post(
    "/api/v1/approvals/{approval_id}/signatures",
    status_code=status.HTTP_201_CREATED,
)
async def sign_approval(
    approval_id: uuid.UUID,
    body: ApprovalSignatureCreate,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Record one party's Ed25519 signature over a pending approval.

    The signature is verified against the subject's enrolled public keys before
    it is stored, so a stored signature is always a valid one.
    """
    scoped = await db.execute(
        select(Approval).where(
            Approval.id == approval_id, Approval.company_id == company_id
        )
    )
    if scoped.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found",
        )

    service = ApprovalService(db)
    try:
        await service.add_signature(approval_id, body.subject, body.signature)
    except SignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    await db.commit()

    collected = await service.count_signatures(approval_id)
    return {"approval_id": approval_id, "signatures": collected}


@router.post(
    "/api/v1/approvals/{approval_id}/reject",
    response_model=ApprovalResponse,
)
async def reject(
    approval_id: uuid.UUID, body: ApprovalDecision, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Reject a pending approval request."""
    existing = await db.execute(
        select(Approval).where(Approval.id == approval_id, Approval.company_id == company_id)
    )
    if existing.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found or not pending",
        )
    approval = await ApprovalService(db).reject(
        approval_id, body.decided_by, body.decision_note
    )
    if approval is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found or not pending",
        )
    return approval
