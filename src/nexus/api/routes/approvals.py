"""Approval API endpoints - governance approval workflows."""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.governance import Approval

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
    """Create a new approval request."""
    approval = Approval(
        company_id=company_id,
        type=body.type,
        requested_by_agent_id=body.requested_by_agent_id,
        payload=body.payload,
        expires_at=body.expires_at,
    )
    db.add(approval)
    await db.flush()
    return approval


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
    """Approve a pending approval request."""
    stmt = (
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == "pending", Approval.company_id == company_id)
        .values(
            status="approved",
            decided_by=body.decided_by,
            decision_note=body.decision_note,
            decided_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found or not pending",
        )

    query = await db.execute(select(Approval).where(Approval.id == approval_id, Approval.company_id == company_id))
    return query.scalar_one()


@router.post(
    "/api/v1/approvals/{approval_id}/reject",
    response_model=ApprovalResponse,
)
async def reject(
    approval_id: uuid.UUID, body: ApprovalDecision, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Reject a pending approval request."""
    stmt = (
        update(Approval)
        .where(Approval.id == approval_id, Approval.status == "pending", Approval.company_id == company_id)
        .values(
            status="rejected",
            decided_by=body.decided_by,
            decision_note=body.decision_note,
            decided_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Approval {approval_id} not found or not pending",
        )

    query = await db.execute(select(Approval).where(Approval.id == approval_id, Approval.company_id == company_id))
    return query.scalar_one()
