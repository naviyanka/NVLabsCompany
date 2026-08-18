"""Cycle Guard - prevents delegation loops and doom-loops in agent hierarchies."""

import uuid
from collections import Counter


# Maximum number of times the same directed edge can appear in a chain
MAX_CYCLE_COUNT: int = 5

# Maximum depth of the delegation chain (ancestor count)
MAX_ANCESTOR_DEPTH: int = 256


class CycleGuardError(Exception):
    """Raised when a delegation cycle or doom-loop is detected."""

    def __init__(
        self,
        source_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
        reason: str,
    ) -> None:
        self.source_agent_id = source_agent_id
        self.target_agent_id = target_agent_id
        self.reason = reason
        super().__init__(
            f"Cycle guard violation: {source_agent_id} -> {target_agent_id}: {reason}"
        )


class CycleGuard:
    """Detects and prevents delegation cycles and doom-loops.

    Pure logic class with no database dependency. Takes the execution
    chain as input and validates that:
    1. No directed edge (A -> B) appears more than MAX_CYCLE_COUNT times.
    2. The total chain depth does not exceed MAX_ANCESTOR_DEPTH.

    This prevents agents from endlessly delegating tasks back and forth
    (doom-loops) or creating infinitely deep delegation chains.
    """

    def __init__(
        self,
        max_cycle_count: int = MAX_CYCLE_COUNT,
        max_ancestor_depth: int = MAX_ANCESTOR_DEPTH,
    ) -> None:
        """Initialize with configurable limits.

        Args:
            max_cycle_count: Max times the same edge can repeat.
            max_ancestor_depth: Max total depth of delegation chain.
        """
        self._max_cycle_count = max_cycle_count
        self._max_ancestor_depth = max_ancestor_depth

    def check_delegation(
        self,
        source_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
        execution_chain: list[tuple[uuid.UUID, uuid.UUID]],
    ) -> bool:
        """Check if a delegation from source to target is safe.

        Validates the proposed delegation against the existing execution
        chain to detect cycles and excessive depth.

        Args:
            source_agent_id: The agent attempting to delegate.
            target_agent_id: The agent being delegated to.
            execution_chain: List of (source, target) tuples representing
                the current delegation history.

        Returns:
            True if the delegation is safe to proceed.

        Raises:
            CycleGuardError: If the delegation would create a cycle or
                exceed depth limits.
        """
        # Check 1: Ancestor depth limit
        proposed_depth = len(execution_chain) + 1
        if proposed_depth > self._max_ancestor_depth:
            raise CycleGuardError(
                source_agent_id,
                target_agent_id,
                f"Delegation chain depth ({proposed_depth}) exceeds "
                f"MAX_ANCESTOR_DEPTH ({self._max_ancestor_depth})",
            )

        # Check 2: Edge repetition count
        proposed_edge = (source_agent_id, target_agent_id)
        edge_counts: Counter[tuple[uuid.UUID, uuid.UUID]] = Counter(execution_chain)
        edge_counts[proposed_edge] += 1

        if edge_counts[proposed_edge] > self._max_cycle_count:
            raise CycleGuardError(
                source_agent_id,
                target_agent_id,
                f"Edge {source_agent_id} -> {target_agent_id} repeated "
                f"{edge_counts[proposed_edge]} times, exceeds "
                f"MAX_CYCLE_COUNT ({self._max_cycle_count})",
            )

        # Check 3: Self-delegation (always a cycle)
        if source_agent_id == target_agent_id:
            # Self-delegation counts as an edge; already handled by edge count
            # but we allow it up to MAX_CYCLE_COUNT
            pass

        return True

    def get_chain_stats(
        self, execution_chain: list[tuple[uuid.UUID, uuid.UUID]]
    ) -> dict[str, int]:
        """Get statistics about the current execution chain.

        Args:
            execution_chain: The current delegation chain.

        Returns:
            Dictionary with depth, unique_edges, max_edge_count.
        """
        edge_counts: Counter[tuple[uuid.UUID, uuid.UUID]] = Counter(execution_chain)
        return {
            "depth": len(execution_chain),
            "unique_edges": len(edge_counts),
            "max_edge_count": max(edge_counts.values()) if edge_counts else 0,
            "max_cycle_count": self._max_cycle_count,
            "max_ancestor_depth": self._max_ancestor_depth,
        }
