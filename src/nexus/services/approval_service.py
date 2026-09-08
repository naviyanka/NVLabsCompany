"""Approval Service - manages governance approval workflows."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.governance.approval_signing import (
    SignatureError,
    canonical_approval_bytes,
    required_signatures_for,
    verify_signature,
)
from nexus.models.governance import (
    Approval,
    ApprovalSignature,
    ApprovalSignerKey,
    DecisionQueue,
)


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
            # Fixed at creation from the type and the amount at stake, so a later
            # payload edit cannot lower the bar on a request already in flight.
            "required_signatures": required_signatures_for(approval_type, payload),
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

        Raises:
            SignatureError: The request needs more distinct signatures than it
                has. Refusing here rather than in the route means every caller
                (route, orchestrator, agent tooling) is held to the same quorum.
        """
        approval = await self.get(approval_id)
        if approval is not None and approval.required_signatures > 1:
            collected = await self.count_signatures(approval_id)
            if collected < approval.required_signatures:
                raise SignatureError(
                    f"approval needs {approval.required_signatures} signatures, "
                    f"has {collected}"
                )

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

    async def count_signatures(self, approval_id: uuid.UUID) -> int:
        """How many distinct signers have signed this approval.

        Distinct by subject, not by row: one operator holding two enrolled keys
        is still one party, which is the whole point of a quorum.

        Args:
            approval_id: The approval to count signatures for.

        Returns:
            The number of distinct signers.
        """
        result = await self._db.execute(
            select(ApprovalSignature.subject)
            .where(ApprovalSignature.approval_id == approval_id)
            .distinct()
        )
        return len(result.scalars().all())

    async def add_signature(
        self,
        approval_id: uuid.UUID,
        subject: str,
        signature_b64: str,
    ) -> ApprovalSignature:
        """Verify and record one signature over a pending approval.

        Args:
            approval_id: The approval being signed.
            subject: The signer, matching an active enrolled key.
            signature_b64: Base64 Ed25519 signature over the approval's
                canonical bytes.

        Returns:
            The recorded ApprovalSignature.

        Raises:
            SignatureError: No such pending approval, no active key for the
                subject, the signature did not verify against any of that
                subject's keys, or the subject already signed.
        """
        approval = await self.get(approval_id)
        if approval is None or approval.status != "pending":
            raise SignatureError("approval is not pending")

        existing = await self._db.execute(
            select(ApprovalSignature).where(
                ApprovalSignature.approval_id == approval_id,
                ApprovalSignature.subject == subject,
            )
        )
        if existing.scalar_one_or_none() is not None:
            # Otherwise one operator signing twice would satisfy a two-party
            # quorum on their own.
            raise SignatureError(f"{subject} has already signed this approval")

        keys = await self._db.execute(
            select(ApprovalSignerKey).where(
                ApprovalSignerKey.company_id == approval.company_id,
                ApprovalSignerKey.subject == subject,
                ApprovalSignerKey.is_active == True,  # noqa: E712
            )
        )
        active_keys = keys.scalars().all()
        if not active_keys:
            raise SignatureError(f"no active signer key for {subject}")

        message = canonical_approval_bytes(
            approval.id, approval.company_id, approval.type, approval.payload
        )
        for key in active_keys:
            try:
                verify_signature(key.public_key, message, signature_b64)
            except SignatureError:
                continue
            record = ApprovalSignature(
                approval_id=approval_id,
                signer_key_id=key.id,
                subject=subject,
                signature=signature_b64,
            )
            self._db.add(record)
            await self._db.flush()
            return record

        raise SignatureError("signature did not verify for any active key")

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
