"""Approval Engine - manages approval requests, decisions, and auto-approve policies.

Supports optional file-backed persistence with atomic writes, approval history
queries, and notification hooks for new pending approvals.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
    for low-risk operations. Optionally persists state to a JSON file using
    atomic writes (tempfile + os.replace) to prevent corruption.
    """

    def __init__(
        self,
        persist_path: Path | None = None,
        on_approval_needed: Callable[[ApprovalRequest], None] | None = None,
    ) -> None:
        """Initialize the approval engine.

        Args:
            persist_path: Optional path to a JSON file for state persistence.
                If None, operates in memory-only mode (backward compatible).
            on_approval_needed: Optional callback invoked when a new approval
                request enters the pending queue (not called for auto-approved).
        """
        self._approvals: dict[uuid.UUID, ApprovalRequest] = {}
        self._policies: list[AutoApprovalPolicy] = []
        self._persist_path = persist_path
        self._on_approval_needed = on_approval_needed

        if self._persist_path is not None:
            self._load()

    def _load(self) -> None:
        """Load persisted state from the JSON file.

        If the file does not exist or is corrupt/invalid, starts with empty state.
        """
        if self._persist_path is None:
            return

        if not self._persist_path.exists():
            return

        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            self._approvals = {}
            for key_str, val in data.items():
                req_id = uuid.UUID(key_str)
                self._approvals[req_id] = self._deserialize_request(val)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, OSError):
            self._approvals = {}

    def _save(self) -> None:
        """Persist current state to file atomically.

        Writes to a temporary file in the same directory, then uses os.replace
        for an atomic swap. This prevents corruption if the process dies mid-write.
        Does nothing if persist_path is None.
        """
        if self._persist_path is None:
            return

        data = {
            str(req_id): self._serialize_request(req)
            for req_id, req in self._approvals.items()
        }
        content = json.dumps(data, indent=2)

        # Ensure parent directory exists
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file in same dir + os.replace
        fd = tempfile.NamedTemporaryFile(
            mode="w",
            dir=self._persist_path.parent,
            suffix=".tmp",
            delete=False,
            encoding="utf-8",
        )
        try:
            fd.write(content)
            fd.flush()
            os.fsync(fd.fileno())
            fd.close()
            os.replace(fd.name, self._persist_path)
        except BaseException:
            fd.close()
            try:
                os.unlink(fd.name)
            except OSError:
                pass
            raise

    @staticmethod
    def _serialize_request(req: ApprovalRequest) -> dict[str, Any]:
        """Serialize an ApprovalRequest to a JSON-compatible dictionary."""
        return {
            "id": str(req.id),
            "company_id": str(req.company_id) if req.company_id else None,
            "type": req.type,
            "requested_by_agent_id": (
                str(req.requested_by_agent_id) if req.requested_by_agent_id else None
            ),
            "payload": req.payload,
            "status": req.status,
            "decision_note": req.decision_note,
            "decided_by": req.decided_by,
            "decided_at": req.decided_at.isoformat() if req.decided_at else None,
            "created_at": req.created_at.isoformat(),
        }

    @staticmethod
    def _deserialize_request(data: dict[str, Any]) -> ApprovalRequest:
        """Deserialize an ApprovalRequest from a dictionary."""
        return ApprovalRequest(
            id=uuid.UUID(data["id"]),
            company_id=uuid.UUID(data["company_id"]) if data.get("company_id") else None,
            type=data.get("type", ""),
            requested_by_agent_id=(
                uuid.UUID(data["requested_by_agent_id"])
                if data.get("requested_by_agent_id")
                else None
            ),
            payload=data.get("payload", {}),
            status=data.get("status", "pending"),
            decision_note=data.get("decision_note"),
            decided_by=data.get("decided_by"),
            decided_at=(
                datetime.fromisoformat(data["decided_at"])
                if data.get("decided_at")
                else None
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
        )

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
        self._save()

        # Notify callback only for pending (not auto-approved) requests
        if request.status == "pending" and self._on_approval_needed is not None:
            self._on_approval_needed(request)

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

        self._save()

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

    def get_approval_history(
        self, company_id: uuid.UUID, limit: int = 50
    ) -> list[ApprovalRequest]:
        """Return resolved approvals for a company, sorted by decision time.

        Filters for approvals with status 'approved' or 'denied', belonging to
        the specified company. Results are sorted by decided_at descending (most
        recent first) and limited to the specified count.

        Args:
            company_id: The company to filter by.
            limit: Maximum number of results to return (default 50).

        Returns:
            List of resolved ApprovalRequest objects, most recent first.
        """
        resolved = [
            req
            for req in self._approvals.values()
            if req.status in ("approved", "denied")
            and req.company_id == company_id
        ]
        resolved.sort(
            key=lambda r: r.decided_at or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return resolved[:limit]
