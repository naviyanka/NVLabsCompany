"""Approval Service - manages governance approval workflows."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.governance import Approval, DecisionQueue


class ApprovalService:
    """Service layer for approval workflow operations.

    Manages the lifecycle of approval requests: creation, approval,
    rejection, and auto-approve policy evaluation.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def request_approval(
        self,
        company_id: uuid.UUID,
        approval_type: str,
        requested_by_agent_id: uuid.UUID,
        payload: dict[str, Any] | None = None,
        expires_at: datetime | None = None,
        approval_id: uuid.UUID | None = None,
    ) -> Approval:
        """Create a new approval request.

        Args:
            company_id: The company this approval belongs to.
            approval_type: Type of operation requiring approval.
            requested_by_agent_id: The agent requesting approval.
            payload: Optional JSON payload with request details.
            expires_at: Optional expiration datetime.
            approval_id: Explicit ID — pass a correlation ID so a retried
                operation resolves to this same approval instead of a new one.

        Returns:
            The newly created Approval instance.
        """
        fields: dict[str, Any] = {
            "company_id": company_id,
            "type": approval_type,
            "requested_by_agent_id": requested_by_agent_id,
            "payload": payload,
            "expires_at": expires_at,
            "status": "pending",
        }
        if approval_id is not None:
            fields["id"] = approval_id
        approval = Approval(**fields)
        self._db.add(approval)
        await self._db.flush()
        return approval

    async def get(self, approval_id: uuid.UUID) -> Approval | None:
        """Fetch an approval by ID.

        Args:
            approval_id: The approval to fetch.

        Returns:
            The Approval, or None when it does not exist.
        """
        result = await self._db.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        return result.scalar_one_or_none()

    async def approve(
        self,
        approval_id: uuid.UUID,
        decided_by: str,
        decision_note: str | None = None,
    ) -> Approval | None:
        """Approve a pending approval request.

        Args:
            approval_id: The approval to approve.
            decided_by: Who approved (user ID or agent ID).
            decision_note: Optional note explaining the decision.

        Returns:
            The updated Approval instance.
        """
        stmt = (
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == "pending")
            .values(
                status="approved",
                decided_by=decided_by,
                decision_note=decision_note,
                decided_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)

        result = await self._db.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        return result.scalar_one_or_none()

    async def reject(
        self,
        approval_id: uuid.UUID,
        decided_by: str,
        decision_note: str | None = None,
    ) -> Approval | None:
        """Reject a pending approval request.

        Args:
            approval_id: The approval to reject.
            decided_by: Who rejected (user ID or agent ID).
            decision_note: Optional note explaining the decision.

        Returns:
            The updated Approval instance.
        """
        stmt = (
            update(Approval)
            .where(Approval.id == approval_id, Approval.status == "pending")
            .values(
                status="rejected",
                decided_by=decided_by,
                decision_note=decision_note,
                decided_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)

        result = await self._db.execute(
            select(Approval).where(Approval.id == approval_id)
        )
        return result.scalar_one_or_none()

    async def get_pending_approvals(
        self,
        company_id: uuid.UUID,
        approval_type: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Approval]:
        """List pending approvals for a company.

        Args:
            company_id: The company to query.
            approval_type: Optional filter by approval type.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of pending Approval instances.
        """
        stmt = select(Approval).where(
            Approval.company_id == company_id,
            Approval.status == "pending",
        )

        if approval_type:
            stmt = stmt.where(Approval.type == approval_type)

        stmt = stmt.offset(offset).limit(limit).order_by(Approval.created_at.asc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def check_auto_approve_policy(
        self,
        company_id: uuid.UUID,
        approval_type: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Check if an operation can be auto-approved based on queue policies.

        Evaluates the decision queue auto-approve policies to determine
        if this type of request can bypass manual approval.

        Args:
            company_id: The company to check policies for.
            approval_type: The type of approval being requested.
            payload: The request payload for policy evaluation.

        Returns:
            True if the operation can be auto-approved.
        """
        # Find decision queues with auto-approve policies
        stmt = select(DecisionQueue).where(
            DecisionQueue.company_id == company_id,
        )
        result = await self._db.execute(stmt)
        queues = result.scalars().all()

        for queue in queues:
            policy = queue.auto_approve_policy
            if policy is None:
                continue

            # Check if this approval type is covered by the policy
            allowed_types = policy.get("allowed_types", [])
            if approval_type in allowed_types:
                # Check cost threshold if applicable
                max_cost = policy.get("max_cost_cents")
                if max_cost is not None and payload:
                    request_cost = payload.get("cost_cents", 0)
                    if request_cost <= max_cost:
                        return True
                elif max_cost is None:
                    return True

        return False
