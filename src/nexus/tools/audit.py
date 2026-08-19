"""Tool audit store - in-memory audit trail with query and statistics capabilities."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from nexus.models.tool_invocation import ToolInvocation


@dataclass
class AuditStats:
    """Aggregated statistics from tool invocation audit records.

    Attributes:
        total_invocations: Total number of recorded invocations.
        success_count: Number of successful invocations.
        error_count: Number of failed invocations (error, timeout, denied, rate_limited).
        total_cost_cents: Sum of cost_cents across all matching invocations.
        avg_duration_ms: Average execution duration in milliseconds.
    """

    total_invocations: int
    success_count: int
    error_count: int
    total_cost_cents: int
    avg_duration_ms: float


class ToolAuditStore:
    """In-memory audit store for tool invocation records.

    Provides recording, filtering, and statistics aggregation for tool
    execution audit trails. Designed for runtime use with optional
    persistence to the database layer.
    """

    def __init__(self) -> None:
        """Initialize the audit store with an empty record list."""
        self._records: list[ToolInvocation] = []

    def record(self, invocation: ToolInvocation) -> None:
        """Store a tool invocation record.

        Args:
            invocation: The ToolInvocation instance to persist.
        """
        self._records.append(invocation)

    def query(
        self,
        agent_id: uuid.UUID | None = None,
        tool_id: uuid.UUID | None = None,
        status: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ToolInvocation]:
        """Query invocation records with optional filters.

        Args:
            agent_id: Filter by the executing agent.
            tool_id: Filter by the target tool.
            status: Filter by execution status (success, error, timeout, denied, rate_limited).
            since: Only return records created at or after this timestamp.
            limit: Maximum number of records to return.

        Returns:
            List of matching ToolInvocation records, most recent first.
        """
        results = self._records

        if agent_id is not None:
            results = [r for r in results if r.agent_id == agent_id]

        if tool_id is not None:
            results = [r for r in results if r.tool_id == tool_id]

        if status is not None:
            results = [r for r in results if r.status == status]

        if since is not None:
            results = [r for r in results if r.created_at >= since]

        # Return most recent first, limited
        return list(reversed(results))[:limit]

    def get_stats(
        self,
        agent_id: uuid.UUID | None = None,
        since: datetime | None = None,
    ) -> AuditStats:
        """Compute aggregated statistics from invocation records.

        Args:
            agent_id: Filter stats to a specific agent.
            since: Only include records created at or after this timestamp.

        Returns:
            AuditStats dataclass with computed aggregates.
        """
        records = self._records

        if agent_id is not None:
            records = [r for r in records if r.agent_id == agent_id]

        if since is not None:
            records = [r for r in records if r.created_at >= since]

        total = len(records)
        success_count = sum(1 for r in records if r.status == "success")
        error_count = total - success_count
        total_cost = sum(r.cost_cents for r in records)
        avg_duration = (
            sum(r.duration_ms for r in records) / total if total > 0 else 0.0
        )

        return AuditStats(
            total_invocations=total,
            success_count=success_count,
            error_count=error_count,
            total_cost_cents=total_cost,
            avg_duration_ms=avg_duration,
        )
