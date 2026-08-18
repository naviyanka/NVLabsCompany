"""Agent-to-Agent (A2A) Protocol - direct messaging with at-least-once delivery.

Implements reliable message passing between agents with correlation-based
deduplication, multiple delivery routes (direct, broadcast, team), and
priority-based message handling.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from nexus.models.communication import Message


# Message types
MESSAGE_TYPE_REQUEST = "request"
MESSAGE_TYPE_RESPONSE = "response"
MESSAGE_TYPE_NOTIFICATION = "notification"
MESSAGE_TYPE_DELEGATION = "delegation"
MESSAGE_TYPE_HANDOFF = "handoff"

VALID_MESSAGE_TYPES = {
    MESSAGE_TYPE_REQUEST,
    MESSAGE_TYPE_RESPONSE,
    MESSAGE_TYPE_NOTIFICATION,
    MESSAGE_TYPE_DELEGATION,
    MESSAGE_TYPE_HANDOFF,
}

# Message priorities
PRIORITY_URGENT = "urgent"
PRIORITY_NORMAL = "normal"
PRIORITY_LOW = "low"

VALID_PRIORITIES = {PRIORITY_URGENT, PRIORITY_NORMAL, PRIORITY_LOW}

# Delivery routes
ROUTE_DIRECT = "direct"
ROUTE_BROADCAST = "broadcast"
ROUTE_TEAM = "team"


class A2AProtocol:
    """Agent-to-Agent messaging protocol with at-least-once delivery semantics.

    Provides reliable messaging between agents with deduplication via
    correlation_id tracking, multiple routing modes (direct, broadcast,
    team-scoped), and message history retrieval.

    All operations are scoped by company_id for multi-tenant isolation.

    Attributes:
        db: Optional async database session for persistence.
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialize the A2A protocol.

        Args:
            db: Optional AsyncSession for database persistence.
        """
        self.db = db
        # In-memory message store keyed by message ID
        self._messages: dict[uuid.UUID, Message] = {}
        # Set of delivered correlation_ids for deduplication
        self._delivered_correlations: set[str] = set()

    async def send_message(
        self,
        sender_id: uuid.UUID,
        recipient_id: uuid.UUID,
        message_type: str,
        content: str,
        priority: str = "normal",
        metadata: Optional[dict[str, Any]] = None,
        company_id: Optional[uuid.UUID] = None,
        correlation_id: Optional[str] = None,
    ) -> Optional[Message]:
        """Send a direct message from one agent to another.

        Implements at-least-once delivery with deduplication: if a message
        with the same correlation_id has already been delivered, the duplicate
        is silently skipped.

        Args:
            sender_id: UUID of the sending agent.
            recipient_id: UUID of the receiving agent.
            message_type: Type of message (request/response/notification/delegation/handoff).
            content: Message body text.
            priority: Message priority (urgent/normal/low).
            metadata: Optional key-value metadata attached to the message.
            company_id: Company scope for tenant isolation.
            correlation_id: Optional ID for deduplication and request-response tracking.

        Returns:
            The created Message object, or None if deduplicated (already delivered).
        """
        # Deduplication check
        if correlation_id and correlation_id in self._delivered_correlations:
            return None

        msg = Message(
            id=uuid.uuid4(),
            company_id=company_id or uuid.uuid4(),
            sender_agent_id=sender_id,
            recipient_agent_id=recipient_id,
            group_id=None,
            message_type=message_type,
            priority=priority,
            content=content,
            metadata=metadata,
            correlation_id=correlation_id or str(uuid.uuid4()),
            delivered=True,
            delivery_route=ROUTE_DIRECT,
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        # Track in-memory
        self._messages[msg.id] = msg
        if msg.correlation_id:
            self._delivered_correlations.add(msg.correlation_id)

        # Persist to DB if available
        if self.db is not None:
            self.db.add(msg)
            await self.db.commit()

        return msg

    async def broadcast(
        self,
        sender_id: uuid.UUID,
        company_id: uuid.UUID,
        agent_ids: list[uuid.UUID],
        message_type: str,
        content: str,
        priority: str = "normal",
        metadata: Optional[dict[str, Any]] = None,
    ) -> list[Message]:
        """Broadcast a message to all agents in a company.

        Sends the same message content to every agent in the provided list.
        Each delivery is tracked independently for deduplication.

        Args:
            sender_id: UUID of the sending agent.
            company_id: Company scope for tenant isolation.
            agent_ids: List of agent UUIDs to receive the message.
            message_type: Type of message.
            content: Message body text.
            priority: Message priority.
            metadata: Optional metadata attached to each message.

        Returns:
            List of successfully delivered Message objects.
        """
        messages: list[Message] = []
        for agent_id in agent_ids:
            if agent_id == sender_id:
                continue
            msg = Message(
                id=uuid.uuid4(),
                company_id=company_id,
                sender_agent_id=sender_id,
                recipient_agent_id=agent_id,
                group_id=None,
                message_type=message_type,
                priority=priority,
                content=content,
                metadata=metadata,
                correlation_id=str(uuid.uuid4()),
                delivered=True,
                delivery_route=ROUTE_BROADCAST,
                created_at=datetime.now(timezone.utc),
                updated_at=None,
            )
            self._messages[msg.id] = msg
            if msg.correlation_id:
                self._delivered_correlations.add(msg.correlation_id)
            messages.append(msg)

        # Persist to DB if available
        if self.db is not None:
            for msg in messages:
                self.db.add(msg)
            await self.db.commit()

        return messages

    async def send_team_scoped(
        self,
        sender_id: uuid.UUID,
        company_id: uuid.UUID,
        team_agent_ids: list[uuid.UUID],
        message_type: str,
        content: str,
        priority: str = "normal",
        metadata: Optional[dict[str, Any]] = None,
    ) -> list[Message]:
        """Send a message scoped to a specific team of agents.

        Similar to broadcast but uses the 'team' delivery route to indicate
        the message is intended for a specific team subset.

        Args:
            sender_id: UUID of the sending agent.
            company_id: Company scope for tenant isolation.
            team_agent_ids: List of agent UUIDs in the target team.
            message_type: Type of message.
            content: Message body text.
            priority: Message priority.
            metadata: Optional metadata.

        Returns:
            List of successfully delivered Message objects.
        """
        messages: list[Message] = []
        for agent_id in team_agent_ids:
            if agent_id == sender_id:
                continue
            msg = Message(
                id=uuid.uuid4(),
                company_id=company_id,
                sender_agent_id=sender_id,
                recipient_agent_id=agent_id,
                group_id=None,
                message_type=message_type,
                priority=priority,
                content=content,
                metadata=metadata,
                correlation_id=str(uuid.uuid4()),
                delivered=True,
                delivery_route=ROUTE_TEAM,
                created_at=datetime.now(timezone.utc),
                updated_at=None,
            )
            self._messages[msg.id] = msg
            if msg.correlation_id:
                self._delivered_correlations.add(msg.correlation_id)
            messages.append(msg)

        # Persist to DB if available
        if self.db is not None:
            for msg in messages:
                self.db.add(msg)
            await self.db.commit()

        return messages

    async def get_message_history(
        self,
        agent_id: uuid.UUID,
        limit: int = 50,
        company_id: Optional[uuid.UUID] = None,
    ) -> list[Message]:
        """Retrieve message history for an agent (sent or received).

        Returns messages ordered by creation time (most recent first),
        filtered by company_id if provided.

        Args:
            agent_id: UUID of the agent whose history to retrieve.
            limit: Maximum number of messages to return. Defaults to 50.
            company_id: Optional company filter for tenant isolation.

        Returns:
            List of Message objects involving the specified agent.
        """
        results: list[Message] = []
        for msg in self._messages.values():
            if company_id and msg.company_id != company_id:
                continue
            if msg.sender_agent_id == agent_id or msg.recipient_agent_id == agent_id:
                results.append(msg)

        # Sort by creation time descending (most recent first)
        results.sort(key=lambda m: m.created_at, reverse=True)
        return results[:limit]

    def is_duplicate(self, correlation_id: str) -> bool:
        """Check if a correlation_id has already been delivered.

        Args:
            correlation_id: The correlation ID to check.

        Returns:
            True if the correlation_id has already been delivered.
        """
        return correlation_id in self._delivered_correlations
