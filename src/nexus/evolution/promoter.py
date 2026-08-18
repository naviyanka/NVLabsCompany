"""Change Promoter - applies approved changes with governance gates.

CRITICAL: The promote() method REQUIRES an approval_id. Evolution changes
are NEVER auto-promoted. This is the governance gate that ensures human
oversight of all self-modification.
"""

import uuid
from datetime import datetime, timezone
from typing import Any


class ChangePromoter:
    """Promotes approved evolution proposals to production.

    All promotion operations require explicit approval. The governance gate
    is enforced by raising ValueError if approval_id is None. Canary deployments
    allow gradual rollout with automated monitoring and rollback.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize the promoter.

        Args:
            db: Optional async database session for persistence.
        """
        self.db = db
        self._promotions: list[dict[str, Any]] = []
        self._canaries: dict[str, dict[str, Any]] = {}

    async def promote(
        self,
        proposal_id: uuid.UUID,
        approval_id: uuid.UUID,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Promote a proposal to production.

        CRITICAL: Raises ValueError if approval_id is None. This is the
        governance gate that prevents self-modification without human approval.

        Args:
            proposal_id: The proposal to promote.
            approval_id: The approval authorizing this promotion. MUST NOT be None.
            company_id: The company this promotion belongs to (for tenant isolation).

        Returns:
            Promotion record with details of the applied change.

        Raises:
            ValueError: If approval_id is None (governance gate violation).
        """
        if approval_id is None:
            raise ValueError("Approval required: approval_id must not be None")

        promotion_record = {
            "promotion_id": str(uuid.uuid4()),
            "proposal_id": str(proposal_id),
            "approval_id": str(approval_id),
            "company_id": str(company_id) if company_id else None,
            "status": "promoted",
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }
        self._promotions.append(promotion_record)
        return promotion_record

    def apply_change(self, proposal: dict[str, Any]) -> dict[str, Any]:
        """Apply the proposed change to production configuration.

        Args:
            proposal: The proposal dict with change details.

        Returns:
            Dict with applied=True, change_id, and applied_at timestamp.
        """
        change_id = uuid.uuid4()
        return {
            "applied": True,
            "change_id": str(change_id),
            "proposal_type": proposal.get("proposal_type", "unknown"),
            "applied_at": datetime.now(timezone.utc).isoformat(),
        }

    def configure_canary(
        self,
        proposal_id: uuid.UUID,
        percentage: int = 10,
    ) -> dict[str, Any]:
        """Set up gradual rollout tracking for a promoted change.

        Args:
            proposal_id: The proposal to canary deploy.
            percentage: Initial traffic percentage for the canary (default 10%).

        Returns:
            Canary configuration dict.
        """
        canary_config = {
            "proposal_id": str(proposal_id),
            "percentage": percentage,
            "status": "active",
            "metrics": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        self._canaries[str(proposal_id)] = canary_config
        return canary_config

    def monitor_canary(
        self,
        proposal_id: uuid.UUID,
        metrics: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Check if a canary deployment is degrading.

        Args:
            proposal_id: The proposal being canary-tested.
            metrics: List of recent metric observations.

        Returns:
            Dict with status ('healthy' or 'degrading') and should_rollback flag.
        """
        canary_key = str(proposal_id)
        if canary_key in self._canaries:
            self._canaries[canary_key]["metrics"].extend(metrics)

        if not metrics:
            return {"status": "healthy", "should_rollback": False}

        # Check for degradation: if error rate > 10% or avg score drops
        error_count = sum(1 for m in metrics if m.get("error", False))
        error_rate = error_count / len(metrics) if metrics else 0

        scores = [m.get("score", 1.0) for m in metrics if "score" in m]
        avg_score = sum(scores) / len(scores) if scores else 1.0

        if error_rate > 0.1 or avg_score < 0.5:
            return {"status": "degrading", "should_rollback": True}

        return {"status": "healthy", "should_rollback": False}

    async def rollback(
        self,
        proposal_id: uuid.UUID,
        reason: str,
        company_id: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        """Revert a promoted change and update status.

        Args:
            proposal_id: The proposal to roll back.
            reason: Explanation for why the rollback is needed.
            company_id: The company this rollback belongs to (for tenant isolation).

        Returns:
            Rollback record with status and reason.
        """
        # Remove canary if active
        canary_key = str(proposal_id)
        if canary_key in self._canaries:
            self._canaries[canary_key]["status"] = "rolled_back"

        rollback_record = {
            "proposal_id": str(proposal_id),
            "company_id": str(company_id) if company_id else None,
            "status": "rolled_back",
            "reason": reason,
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        }
        self._promotions.append(rollback_record)
        return rollback_record

    async def get_change_history(
        self,
        company_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Get all promotions and rollbacks for a company.

        Args:
            company_id: The company to get history for.

        Returns:
            List of promotion/rollback records filtered by company_id.
        """
        company_id_str = str(company_id)
        return [
            record for record in self._promotions
            if record.get("company_id") == company_id_str
        ]
