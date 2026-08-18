"""Approval Engine - manages approval requests, decisions, and auto-approve policies."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ApprovalRequest:
    """A request for approval before executing a gated operation.

    Attributes:
        id: Unique approval identifier.
        company_id: Company scope.
        type: The approval type (e.g., budget_override, tool_access, deployment).
        requested_by_agent_id: The agent that submitted the request.
        payload: Data describing what is being requested.
        status: Current status (pending, approved, denied, expired).
        decision_note: Explanation for the decision.
        decided_by: Who made the decision (user ID or 'auto').
        decided_at: When the decision was made.
        created_at: When the request was created.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_id: uuid.UUID | None = None
    type: str = ""
    requested_by_agent_id: uuid.UUID | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    decision_note: str | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class AutoApprovalPolicy:
    """Policy that defines conditions for automatic approval.

    Attributes:
        id: Unique policy identifier.
        company_id: Company scope.
        approval_type: The type of approval this policy applies to.
        conditions: Conditions that must all be met for auto-approval.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_id: uuid.UUID | None = None
    approval_type: str = ""
    conditions: dict[str, Any] = field(default_factory=dict)


class ApprovalEngine:
    """Manages the approval lifecycle: submission, auto-approve checks, and decisions.

    Supports human-in-the-loop gates with configurable auto-approval policies
    for low-risk operations.
    """

    def __init__(self) -> None:
        """Initialize the approval engine."""
        self._approvals: dict[uuid.UUID, ApprovalRequest] = {}
        self._policies: list[AutoApprovalPolicy] = []

    def add_policy(self, policy: AutoApprovalPolicy) -> None:
        """Add an auto-approval policy.

        Args:
            policy: The policy to add.
        """
        self._policies.append(policy)

    async def submit_for_approval(
        self,
        company_id: uuid.UUID,
        approval_type: str,
        requested_by_agent_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> ApprovalRequest:
        """Submit a new approval request.

        Checks auto-approval policies first. If the request matches a
        policy, it is automatically approved. Otherwise, it enters the
        pending queue for human review.

        Args:
            company_id: Company scope.
            approval_type: Type of approval being requested.
            requested_by_agent_id: The requesting agent.
            payload: Details of the request.

        Returns:
            The created ApprovalRequest (may be pre-approved).
        """
        request = ApprovalRequest(
            company_id=company_id,
            type=approval_type,
            requested_by_agent_id=requested_by_agent_id,
            payload=payload,
        )

        # Check auto-approval
        if self.check_auto_approve(request, self._policies):
            request.status = "approved"
            request.decided_by = "auto"
            request.decision_note = "Auto-approved by policy"
            request.decided_at = datetime.now(timezone.utc)

        self._approvals[request.id] = request
        return request

    async def process_approval(
        self,
        approval_id: uuid.UUID,
        decision: str,
        decided_by: str,
        note: str | None = None,
    ) -> ApprovalRequest | None:
        """Process a pending approval with a human decision.

        Args:
            approval_id: The approval to process.
            decision: The decision ('approved' or 'denied').
            decided_by: Identifier of who made the decision.
            note: Optional explanation for the decision.

        Returns:
            The updated ApprovalRequest, or None if not found.
        """
        request = self._approvals.get(approval_id)
        if not request:
            return None

        if request.status != "pending":
            return request

        request.status = decision
        request.decided_by = decided_by
        request.decision_note = note
        request.decided_at = datetime.now(timezone.utc)

        return request

    def check_auto_approve(
        self,
        request: ApprovalRequest,
        policies: list[AutoApprovalPolicy],
    ) -> bool:
        """Check if a request qualifies for automatic approval.

        Auto-approves based on:
        - Cost below threshold
        - Trusted agent (agent_id in trusted list)
        - Pre-approved action type

        Args:
            request: The approval request to check.
            policies: List of policies to evaluate against.

        Returns:
            True if the request should be auto-approved.
        """
        for policy in policies:
            if policy.approval_type != request.type:
                continue
            if policy.company_id and policy.company_id != request.company_id:
                continue

            if self._matches_policy(request, policy):
                return True

        return False

    def _matches_policy(
        self, request: ApprovalRequest, policy: AutoApprovalPolicy
    ) -> bool:
        """Check if a request matches all conditions of a policy.

        Args:
            request: The request to check.
            policy: The policy with conditions.

        Returns:
            True if all conditions are satisfied.
        """
        conditions = policy.conditions

        # Check cost threshold
        max_cost = conditions.get("max_cost_cents")
        if max_cost is not None:
            request_cost = request.payload.get("cost_cents", 0)
            if request_cost > max_cost:
                return False

        # Check trusted agents
        trusted_agents = conditions.get("trusted_agent_ids")
        if trusted_agents is not None:
            agent_str = str(request.requested_by_agent_id)
            if agent_str not in trusted_agents:
                return False

        # Check pre-approved action types
        approved_actions = conditions.get("approved_actions")
        if approved_actions is not None:
            action = request.payload.get("action")
            if action not in approved_actions:
                return False

        return True

    def get_pending_approvals(
        self, company_id: uuid.UUID | None = None
    ) -> list[ApprovalRequest]:
        """Get all pending approval requests.

        Args:
            company_id: Filter by company. None means all.

        Returns:
            List of pending ApprovalRequest objects.
        """
        results: list[ApprovalRequest] = []
        for request in self._approvals.values():
            if request.status != "pending":
                continue
            if company_id and request.company_id != company_id:
                continue
            results.append(request)
        return results

    def get_approval(self, approval_id: uuid.UUID) -> ApprovalRequest | None:
        """Retrieve an approval request by ID.

        Args:
            approval_id: The approval identifier.

        Returns:
            The ApprovalRequest, or None if not found.
        """
        return self._approvals.get(approval_id)
