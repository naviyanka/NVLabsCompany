"""A2A Router - structured communication modes for agent-to-agent messaging.

Provides three communication modes:
- notify: Fire-and-forget message delivery
- consult: Request-response with timeout tracking
- delegate: Full task delegation with CycleGuard integration
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from nexus.runtime.cycle_guard import CycleGuard, CycleGuardError  # noqa: F401

# Stable namespace for deterministic A2A identifiers (Phase 4.1).
A2A_NAMESPACE = uuid.UUID("6f1c9a2e-6b3d-5f4a-8c7b-1d2e3f4a5b6c")


def correlation_id_for(source_run_id: object, tool_call_id: object) -> str:
    """Derive a deterministic correlation ID from a run and tool call.

    Replaying the same workflow step yields the same correlation ID, which is
    what makes delegation dedupe possible.

    Args:
        source_run_id: Identifier of the run issuing the delegation.
        tool_call_id: Identifier of the tool call inside that run.

    Returns:
        The UUIDv5 correlation ID as a string.
    """
    return str(uuid.uuid5(A2A_NAMESPACE, f"corr:{source_run_id}:{tool_call_id}"))


def execution_id_for(source_run_id: object, tool_call_id: object) -> uuid.UUID:
    """Derive a deterministic execution ID from a run and tool call.

    Args:
        source_run_id: Identifier of the run issuing the delegation.
        tool_call_id: Identifier of the tool call inside that run.

    Returns:
        The UUIDv5 execution ID.
    """
    return uuid.uuid5(A2A_NAMESPACE, f"exec:{source_run_id}:{tool_call_id}")


class CommunicationMode(Enum):
    """Supported communication modes for A2A messaging."""

    notify = "notify"
    consult = "consult"
    delegate = "delegate"


@dataclass
class A2AMessage:
    """Structured message for agent-to-agent communication.

    Attributes:
        id: Unique message identifier.
        sender: UUID of the sending agent.
        recipient: UUID of the receiving agent.
        mode: Communication mode (notify, consult, delegate).
        payload: Message content as a dictionary.
        correlation_id: Identifier for correlating request/response pairs.
        timeout_seconds: Optional timeout for consult mode messages.
        created_at: Timestamp when the message was created.
        response: Optional response payload (populated by respond()).
        response_received_at: Timestamp when a response was received.
        status: Message lifecycle status (pending/delivered/responded/timed_out).
    """

    id: uuid.UUID
    sender: uuid.UUID
    recipient: uuid.UUID
    mode: CommunicationMode
    payload: dict
    correlation_id: str
    timeout_seconds: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    response: dict | None = None
    response_received_at: datetime | None = None
    status: str = "pending"


class A2ARouter:
    """Routes agent-to-agent messages with permission checks and mode-specific behavior.

    Supports three communication modes:
    - notify: Immediate delivery, no response tracking.
    - consult: Tracks pending messages, supports respond() and timeout detection.
    - delegate: Validates with CycleGuard before delivery to prevent infinite loops.

    Attributes:
        cycle_guard: Optional CycleGuard instance for delegate mode validation.
    """

    def __init__(
        self,
        cycle_guard: CycleGuard | None = None,
        permissions: dict | None = None,
    ) -> None:
        """Initialize the A2A router.

        Args:
            cycle_guard: Optional CycleGuard for delegate mode loop detection.
            permissions: Optional initial permissions dict mapping
                (sender, recipient) -> list[CommunicationMode].
        """
        self._cycle_guard = cycle_guard
        self._permissions: dict[tuple[uuid.UUID, uuid.UUID], list[CommunicationMode]] = (
            permissions if permissions is not None else {}
        )
        self._pending_consults: dict[str, A2AMessage] = {}
        self._execution_chain: list[tuple[uuid.UUID, uuid.UUID]] = []
        self._delegations: dict[str, A2AMessage] = {}

    def send(self, message: A2AMessage) -> A2AMessage:
        """Route a message based on its communication mode.

        For notify mode: marks as delivered immediately.
        For consult mode: marks as pending and tracks for response.
        For delegate mode: checks with CycleGuard first, raises CycleGuardError
            if a loop is detected, then marks as delivered.

        Args:
            message: The A2AMessage to route.

        Returns:
            The message with updated status.

        Raises:
            CycleGuardError: If delegate mode detects an infinite loop.
            PermissionError: If the sender lacks permission for this mode.
        """
        if not self.check_permission(message.sender, message.recipient, message.mode):
            raise PermissionError(
                f"Agent {message.sender} does not have '{message.mode.value}' "
                f"permission for agent {message.recipient}"
            )

        if message.mode == CommunicationMode.notify:
            message.status = "delivered"
        elif message.mode == CommunicationMode.consult:
            message.status = "pending"
            self._pending_consults[message.correlation_id] = message
        elif message.mode == CommunicationMode.delegate:
            existing = self._delegations.get(message.correlation_id)
            if existing is not None:
                return existing
            if self._cycle_guard is not None:
                self._cycle_guard.check_delegation(
                    message.sender, message.recipient, self._execution_chain
                )
            self._execution_chain.append((message.sender, message.recipient))
            message.status = "delivered"
            self._delegations[message.correlation_id] = message

        return message

    def check_permission(
        self,
        sender: uuid.UUID,
        recipient: uuid.UUID,
        mode: CommunicationMode,
    ) -> bool:
        """Check if a sender has permission to communicate with a recipient in a given mode.

        If no permissions have been registered at all, all communications are allowed
        (open by default). Once any permission is registered, only explicitly allowed
        communications are permitted.

        Args:
            sender: The sending agent's UUID.
            recipient: The receiving agent's UUID.
            mode: The communication mode to check.

        Returns:
            True if the communication is allowed, False otherwise.
        """
        if not self._permissions:
            return True

        key = (sender, recipient)
        if key not in self._permissions:
            return False

        return mode in self._permissions[key]

    def register_permission(
        self,
        sender: uuid.UUID,
        recipient: uuid.UUID,
        allowed_modes: list[CommunicationMode],
    ) -> None:
        """Register allowed communication modes between two agents.

        Args:
            sender: The sending agent's UUID.
            recipient: The receiving agent's UUID.
            allowed_modes: List of CommunicationMode values allowed.
        """
        self._permissions[(sender, recipient)] = allowed_modes

    def respond(self, correlation_id: str, response_payload: dict) -> A2AMessage | None:
        """Resolve a pending consult message with a response.

        Args:
            correlation_id: The correlation_id of the pending consult message.
            response_payload: The response data.

        Returns:
            The updated A2AMessage if found, or None if no pending message matches.
        """
        message = self._pending_consults.get(correlation_id)
        if message is None:
            return None

        message.response = response_payload
        message.response_received_at = datetime.now(timezone.utc)
        message.status = "responded"
        del self._pending_consults[correlation_id]
        return message

    def get_pending_consults(self, agent_id: uuid.UUID) -> list[A2AMessage]:
        """Get all unresolved consult messages for a specific agent.

        Args:
            agent_id: The UUID of the agent to query pending consults for.

        Returns:
            List of pending A2AMessage objects where the agent is the recipient.
        """
        return [
            msg
            for msg in self._pending_consults.values()
            if msg.recipient == agent_id
        ]

    def check_timeouts(self) -> list[A2AMessage]:
        """Check for and mark expired consult messages as timed_out.

        Returns:
            List of messages that were marked as timed_out.
        """
        now = datetime.now(timezone.utc)
        timed_out: list[A2AMessage] = []
        expired_ids: list[str] = []

        for correlation_id, message in self._pending_consults.items():
            if message.timeout_seconds is not None:
                elapsed = (now - message.created_at).total_seconds()
                if elapsed >= message.timeout_seconds:
                    message.status = "timed_out"
                    timed_out.append(message)
                    expired_ids.append(correlation_id)

        for cid in expired_ids:
            del self._pending_consults[cid]

        return timed_out

    def get_execution_chain(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        """Get the current delegation chain for CycleGuard checks.

        Returns:
            List of (source, target) UUID tuples representing the delegation history.
        """
        return list(self._execution_chain)
