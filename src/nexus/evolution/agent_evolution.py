"""Agent Evolution - versioned agent configuration with approval-gated promotion.

Manages the lifecycle of agent configurations: creating candidates, optimizing
model selection, tools, and budget, and promoting improvements. All promotions
require explicit approval gates.
"""

import uuid
from datetime import datetime, timezone
from typing import Any


class AgentEvolution:
    """Manages agent version lifecycle with approval-gated promotion.

    Tracks agent configuration versions, provides optimization recommendations
    for model selection, tool usage, and budget. Promotion to active status
    ALWAYS requires an approval_id.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize agent evolution manager.

        Args:
            db: Optional async database session for persistence.
        """
        self.db = db
        self._versions: list[dict[str, Any]] = []

    async def create_candidate(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        proposed_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new agent version candidate.

        Args:
            company_id: The company owning the agent.
            agent_id: The agent to create a new version for.
            proposed_config: The proposed configuration snapshot.

        Returns:
            The created version record.
        """
        existing_versions = [
            v for v in self._versions
            if v["agent_id"] == str(agent_id) and v["company_id"] == str(company_id)
        ]
        version_number = len(existing_versions) + 1

        version_record = {
            "id": str(uuid.uuid4()),
            "company_id": str(company_id),
            "agent_id": str(agent_id),
            "version_number": version_number,
            "config_snapshot": proposed_config,
            "performance_score": None,
            "is_active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._versions.append(version_record)
        return version_record

    def optimize_model_selection(
        self,
        task_type_performance: dict[str, dict[str, float]],
    ) -> dict[str, str]:
        """Recommend the best model per task type based on performance data.

        Args:
            task_type_performance: Dict mapping task_type to {model_name: score}.
                Example: {"summarization": {"gpt-4": 0.9, "gpt-3.5": 0.7}}

        Returns:
            Dict mapping task_type to recommended model name.
        """
        recommendations: dict[str, str] = {}
        for task_type, model_scores in task_type_performance.items():
            if model_scores:
                best_model = max(model_scores.items(), key=lambda x: x[1])
                recommendations[task_type] = best_model[0]

        return recommendations

    def optimize_tools(
        self,
        tool_usage_stats: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Recommend tool set changes based on usage statistics.

        Args:
            tool_usage_stats: Dict with tool names as keys and usage stats as values.
                Each tool stat should have 'usage_count', 'success_rate', and
                'avg_duration_ms' fields.

        Returns:
            Dict with 'add', 'remove', and 'keep' lists of tool names.
        """
        add: list[str] = []
        remove: list[str] = []
        keep: list[str] = []

        for tool_name, stats in tool_usage_stats.items():
            if isinstance(stats, dict):
                success_rate = stats.get("success_rate", 0.0)
                usage_count = stats.get("usage_count", 0)

                if success_rate < 0.3 and usage_count > 5:
                    # Low success rate with sufficient samples -> remove
                    remove.append(tool_name)
                elif success_rate >= 0.7:
                    # Good success rate -> keep
                    keep.append(tool_name)
                elif usage_count == 0:
                    # Never used -> consider removing
                    remove.append(tool_name)
                else:
                    # Moderate performance -> keep for now
                    keep.append(tool_name)

        # Suggest additions based on gaps (tools with suggested=True)
        suggested_tools = [
            name for name, stats in tool_usage_stats.items()
            if isinstance(stats, dict) and stats.get("suggested", False)
        ]
        add.extend(suggested_tools)

        return {
            "add": add,
            "remove": remove,
            "keep": keep,
        }

    def optimize_budget(
        self,
        cost_history: list[float],
        quality_history: list[float],
    ) -> dict[str, Any]:
        """Recommend budget adjustment based on cost and quality history.

        Args:
            cost_history: List of recent costs in cents.
            quality_history: List of recent quality scores (0-1).

        Returns:
            Dict with recommendation ('increase'/'decrease'/'maintain'),
            suggested_amount_cents, and reason.
        """
        if not cost_history or not quality_history:
            return {
                "recommendation": "maintain",
                "suggested_amount_cents": 0,
                "reason": "Insufficient data for budget optimization",
            }

        avg_cost = sum(cost_history) / len(cost_history)
        avg_quality = sum(quality_history) / len(quality_history)

        # Check trend in quality
        recent_quality = quality_history[-3:] if len(quality_history) >= 3 else quality_history
        avg_recent_quality = sum(recent_quality) / len(recent_quality)

        if avg_recent_quality < 0.5 and avg_cost < 500:
            # Low quality, low cost -> suggest increase
            suggested_increase = int(avg_cost * 0.5)
            return {
                "recommendation": "increase",
                "suggested_amount_cents": suggested_increase,
                "reason": f"Quality ({avg_recent_quality:.2f}) is below threshold. "
                          f"Increasing budget by {suggested_increase} cents may improve model quality.",
            }
        elif avg_recent_quality > 0.85 and avg_cost > 300:
            # High quality, high cost -> suggest decrease
            suggested_decrease = int(avg_cost * 0.2)
            return {
                "recommendation": "decrease",
                "suggested_amount_cents": suggested_decrease,
                "reason": f"Quality ({avg_recent_quality:.2f}) is excellent. "
                          f"Can reduce budget by {suggested_decrease} cents without impacting quality.",
            }
        else:
            return {
                "recommendation": "maintain",
                "suggested_amount_cents": 0,
                "reason": f"Current balance of quality ({avg_recent_quality:.2f}) "
                          f"and cost ({avg_cost:.0f} cents) is acceptable.",
            }

    async def promote_candidate(
        self,
        version_id: uuid.UUID,
        approval_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Promote an agent version candidate to active status.

        CRITICAL: Raises ValueError if approval_id is None. This is the
        governance gate that prevents auto-promotion without human approval.

        Args:
            version_id: The version to promote.
            approval_id: The approval authorizing this promotion. MUST NOT be None.

        Returns:
            The promoted version record.

        Raises:
            ValueError: If approval_id is None (governance gate violation).
        """
        if approval_id is None:
            raise ValueError("Approval required: approval_id must not be None")

        version_str = str(version_id)
        promoted_version = None

        for version in self._versions:
            if version["id"] == version_str:
                # Deactivate other versions of the same agent
                agent_id = version["agent_id"]
                company_id = version["company_id"]
                for v in self._versions:
                    if v["agent_id"] == agent_id and v["company_id"] == company_id:
                        v["is_active"] = False

                # Activate this version
                version["is_active"] = True
                promoted_version = version
                break

        if promoted_version is None:
            raise ValueError(f"Version {version_id} not found")

        return {
            **promoted_version,
            "approval_id": str(approval_id),
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_evolution_history(
        self,
        agent_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Get all versions of an agent.

        Args:
            agent_id: The agent to get history for.
            company_id: The company owning the agent.

        Returns:
            List of all version records sorted by version number.
        """
        versions = [
            v for v in self._versions
            if v["agent_id"] == str(agent_id) and v["company_id"] == str(company_id)
        ]
        versions.sort(key=lambda v: v["version_number"])
        return versions
