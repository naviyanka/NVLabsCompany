"""Rollback Manager - Change rollback system for reversible operations.

Tracks all state changes as reversible operations and provides mechanisms
for single-action rollback, checkpoint restore, and cascading rollback.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class Operation:
    """A recorded reversible operation.

    Attributes:
        id: Unique operation identifier.
        action: Description of the action performed.
        resource_type: Type of resource affected.
        resource_id: Identifier of the affected resource.
        previous_state: State before the operation.
        new_state: State after the operation.
        timestamp: When the operation occurred.
        dependencies: List of operation IDs that depend on this one.
        performed_by: Who performed the operation.
        rolled_back: Whether this operation has been rolled back.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    action: str = ""
    resource_type: str = ""
    resource_id: str = ""
    previous_state: dict[str, Any] = field(default_factory=dict)
    new_state: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    dependencies: list[uuid.UUID] = field(default_factory=list)
    performed_by: str = ""
    rolled_back: bool = False


@dataclass
class Checkpoint:
    """A named checkpoint representing a known good state.

    Attributes:
        id: Unique checkpoint identifier.
        name: Human-readable name for the checkpoint.
        created_at: When the checkpoint was created.
        operation_index: Index into the operations list at checkpoint time.
        description: Optional description of the checkpoint state.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    operation_index: int = 0
    description: str = ""


@dataclass
class RollbackResult:
    """Result of a rollback attempt.

    Attributes:
        success: Whether the rollback completed.
        rolled_back_operations: Operations that were rolled back.
        blocked_reason: If not successful, why it was blocked.
    """

    success: bool = False
    rolled_back_operations: list[Operation] = field(default_factory=list)
    blocked_reason: str = ""


class RollbackManager:
    """Manages reversible operations with rollback capabilities.

    Records all state changes as reversible operations and provides:
    - Single operation rollback
    - Checkpoint-based rollback
    - Cascading rollback (undo + all dependents)
    - Safety checks before rollback execution
    """

    def __init__(self) -> None:
        """Initialize the rollback manager."""
        self._operations: list[Operation] = []
        self._checkpoints: list[Checkpoint] = []
        self._rollback_history: list[RollbackResult] = []

    def record_operation(
        self,
        action: str,
        resource_type: str,
        resource_id: str,
        previous_state: dict[str, Any],
        new_state: dict[str, Any],
        dependencies: list[uuid.UUID] | None = None,
        performed_by: str = "",
    ) -> Operation:
        """Record a new reversible operation.

        Args:
            action: Description of the action performed.
            resource_type: Type of resource affected.
            resource_id: Identifier of the affected resource.
            previous_state: State before the operation.
            new_state: State after the operation.
            dependencies: Operations this one depends on.
            performed_by: Who performed the operation.

        Returns:
            The recorded Operation.
        """
        op = Operation(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            previous_state=previous_state,
            new_state=new_state,
            dependencies=dependencies or [],
            performed_by=performed_by,
        )
        self._operations.append(op)
        return op

    def create_checkpoint(self, name: str, description: str = "") -> Checkpoint:
        """Create a named checkpoint at the current state.

        Args:
            name: Human-readable name for the checkpoint.
            description: Optional description of the state.

        Returns:
            The created Checkpoint.
        """
        checkpoint = Checkpoint(
            name=name,
            operation_index=len(self._operations),
            description=description,
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def safety_check(self, operation_id: uuid.UUID) -> tuple[bool, str]:
        """Check if an operation can be safely rolled back.

        Verifies that no newer operations depend on the target operation.
        If dependencies exist, the rollback is unsafe.

        Args:
            operation_id: The operation to check.

        Returns:
            A tuple of (is_safe, reason). is_safe is True if rollback is safe.
        """
        # Find the operation
        target_op = None
        for op in self._operations:
            if op.id == operation_id:
                target_op = op
                break

        if target_op is None:
            return False, f"Operation {operation_id} not found"

        if target_op.rolled_back:
            return False, "Operation has already been rolled back"

        # Check if any non-rolled-back operations depend on this one
        dependents = self._find_dependents(operation_id)
        active_dependents = [d for d in dependents if not d.rolled_back]

        if active_dependents:
            dependent_ids = [str(d.id)[:8] for d in active_dependents]
            return False, (
                f"Cannot rollback: {len(active_dependents)} active operation(s) "
                f"depend on this one: {', '.join(dependent_ids)}"
            )

        return True, "Safe to rollback"

    def rollback_operation(self, operation_id: uuid.UUID) -> RollbackResult:
        """Rollback a single operation after safety check.

        Args:
            operation_id: The operation to rollback.

        Returns:
            RollbackResult indicating success or failure.
        """
        is_safe, reason = self.safety_check(operation_id)
        if not is_safe:
            result = RollbackResult(success=False, blocked_reason=reason)
            self._rollback_history.append(result)
            return result

        target_op = self._find_operation(operation_id)
        if target_op is None:
            result = RollbackResult(
                success=False, blocked_reason=f"Operation {operation_id} not found"
            )
            self._rollback_history.append(result)
            return result

        target_op.rolled_back = True
        result = RollbackResult(success=True, rolled_back_operations=[target_op])
        self._rollback_history.append(result)
        return result

    def rollback_to_checkpoint(self, checkpoint_id: uuid.UUID) -> RollbackResult:
        """Rollback all operations after a checkpoint.

        Restores the state to what it was at the checkpoint by rolling back
        all operations recorded after it, in reverse order.

        Args:
            checkpoint_id: The checkpoint to restore to.

        Returns:
            RollbackResult with all rolled back operations.
        """
        target_checkpoint = None
        for cp in self._checkpoints:
            if cp.id == checkpoint_id:
                target_checkpoint = cp
                break

        if target_checkpoint is None:
            result = RollbackResult(
                success=False,
                blocked_reason=f"Checkpoint {checkpoint_id} not found",
            )
            self._rollback_history.append(result)
            return result

        # Rollback all operations after the checkpoint in reverse order
        ops_to_rollback = [
            op
            for op in self._operations[target_checkpoint.operation_index:]
            if not op.rolled_back
        ]

        for op in reversed(ops_to_rollback):
            op.rolled_back = True

        result = RollbackResult(
            success=True,
            rolled_back_operations=list(reversed(ops_to_rollback)),
        )
        self._rollback_history.append(result)
        return result

    def cascading_rollback(self, operation_id: uuid.UUID) -> RollbackResult:
        """Rollback an operation and all operations that depend on it.

        Performs a cascading rollback by finding all direct and transitive
        dependents and rolling them back first (in reverse order), then
        rolling back the target operation.

        Args:
            operation_id: The root operation to rollback.

        Returns:
            RollbackResult with all rolled back operations.
        """
        target_op = self._find_operation(operation_id)
        if target_op is None:
            result = RollbackResult(
                success=False,
                blocked_reason=f"Operation {operation_id} not found",
            )
            self._rollback_history.append(result)
            return result

        if target_op.rolled_back:
            result = RollbackResult(
                success=False,
                blocked_reason="Operation has already been rolled back",
            )
            self._rollback_history.append(result)
            return result

        # Find all dependents (transitive)
        all_dependents = self._find_all_dependents(operation_id)
        active_dependents = [d for d in all_dependents if not d.rolled_back]

        # Rollback dependents in reverse order (most recent first)
        rolled_back: list[Operation] = []
        for dep in reversed(active_dependents):
            dep.rolled_back = True
            rolled_back.append(dep)

        # Rollback the target operation
        target_op.rolled_back = True
        rolled_back.append(target_op)

        result = RollbackResult(success=True, rolled_back_operations=rolled_back)
        self._rollback_history.append(result)
        return result

    def get_rollback_history(self) -> list[RollbackResult]:
        """Get the history of all rollback attempts.

        Returns:
            List of RollbackResult objects.
        """
        return list(self._rollback_history)

    def get_operations(self, include_rolled_back: bool = False) -> list[Operation]:
        """Get all recorded operations.

        Args:
            include_rolled_back: Whether to include rolled-back operations.

        Returns:
            List of Operation objects.
        """
        if include_rolled_back:
            return list(self._operations)
        return [op for op in self._operations if not op.rolled_back]

    def get_checkpoints(self) -> list[Checkpoint]:
        """Get all checkpoints.

        Returns:
            List of Checkpoint objects.
        """
        return list(self._checkpoints)

    def _find_operation(self, operation_id: uuid.UUID) -> Operation | None:
        """Find an operation by ID.

        Args:
            operation_id: The operation to find.

        Returns:
            The Operation, or None if not found.
        """
        for op in self._operations:
            if op.id == operation_id:
                return op
        return None

    def _find_dependents(self, operation_id: uuid.UUID) -> list[Operation]:
        """Find operations that directly depend on the given operation.

        Args:
            operation_id: The operation to find dependents of.

        Returns:
            List of operations that depend on this one.
        """
        return [
            op
            for op in self._operations
            if operation_id in op.dependencies
        ]

    def _find_all_dependents(self, operation_id: uuid.UUID) -> list[Operation]:
        """Find all transitive dependents of an operation.

        Args:
            operation_id: The root operation.

        Returns:
            List of all operations that directly or transitively depend on this one.
        """
        all_deps: list[Operation] = []
        visited: set[uuid.UUID] = set()
        queue = [operation_id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            direct_deps = self._find_dependents(current_id)
            for dep in direct_deps:
                if dep.id not in visited:
                    all_deps.append(dep)
                    queue.append(dep.id)

        return all_deps
