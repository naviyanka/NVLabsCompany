"""Group communication manager for multi-agent conversations and handoffs.

Provides group creation, membership management, message broadcasting within
groups, agent mentions, and task handoffs between group members.
"""

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Optional

from nexus.models.communication import Group, GroupMember, Message
from nexus.runtime.cycle_guard import CycleGuard, CycleGuardError  # noqa: F401


@dataclass(frozen=True)
class HandoffIntent:
    """An immutable, fully-resolved decision to deliver one handoff.

    Staging resolves who the handoff goes to and what it carries; freezing the
    result means the delivery transaction cannot drift from what was decided.

    Attributes:
        group_id: UUID of the group context.
        company_id: Tenant that owns the handoff.
        from_agent_id: UUID of the agent delegating the task.
        to_agent_id: UUID of the agent receiving the task.
        task_context: Description of the task being handed off.
        correlation_id: Deterministic identifier for this handoff.
        metadata: Read-only metadata applied to the delivered message.
    """

    group_id: uuid.UUID
    company_id: uuid.UUID
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    task_context: str
    correlation_id: str
    metadata: Mapping[str, Any] = field(default_factory=dict)


class GroupManager:
    """Manages group-based communication for multi-agent collaboration.

    Supports creating groups, managing membership, broadcasting messages
    to all group members, mentioning specific agents, and handing off
    tasks between agents within a group context.

    All operations are scoped by company_id for multi-tenant isolation.

    Attributes:
        db: Optional async database session for persistence.
    """

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialize the GroupManager.

        Args:
            db: Optional AsyncSession for database persistence.
        """
        self.db = db
        # In-memory stores
        self._groups: dict[uuid.UUID, Group] = {}
        self._members: dict[uuid.UUID, list[GroupMember]] = {}  # group_id -> members
        self._messages: dict[uuid.UUID, list[Message]] = {}  # group_id -> messages
        # Frozen handoff intents already delivered, keyed by correlation_id.
        self._delivered_handoffs: dict[str, Message] = {}
        # Handoff edges per group, for cycle detection.
        self._handoff_chains: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID]]] = {}
        self._cycle_guard = CycleGuard()

    async def create_group(
        self,
        company_id: uuid.UUID,
        name: str,
        agent_ids: list[uuid.UUID],
        description: Optional[str] = None,
    ) -> Group:
        """Create a new communication group and add initial members.

        Args:
            company_id: Company scope for tenant isolation.
            name: Human-readable group name.
            agent_ids: List of agent UUIDs to add as initial members.
            description: Optional description of the group purpose.

        Returns:
            The created Group object.
        """
        group = Group(
            id=uuid.uuid4(),
            company_id=company_id,
            name=name,
            description=description,
            created_at=datetime.now(timezone.utc),
        )
        self._groups[group.id] = group
        self._members[group.id] = []
        self._messages[group.id] = []

        # Add initial members
        for agent_id in agent_ids:
            member = GroupMember(
                id=uuid.uuid4(),
                group_id=group.id,
                agent_id=agent_id,
                role="member",
                joined_at=datetime.now(timezone.utc),
            )
            self._members[group.id].append(member)

        # Persist to DB if available
        if self.db is not None:
            self.db.add(group)
            for member in self._members[group.id]:
                self.db.add(member)
            await self.db.commit()

        return group

    async def add_member(
        self,
        group_id: uuid.UUID,
        agent_id: uuid.UUID,
        role: str = "member",
    ) -> Optional[GroupMember]:
        """Add a new member to a group.

        Args:
            group_id: UUID of the target group.
            agent_id: UUID of the agent to add.
            role: Role within the group (e.g., member, admin, observer).

        Returns:
            The created GroupMember, or None if the group does not exist.
        """
        if group_id not in self._groups:
            return None

        # Check if agent is already a member
        existing = self._members.get(group_id, [])
        for m in existing:
            if m.agent_id == agent_id:
                return m

        member = GroupMember(
            id=uuid.uuid4(),
            group_id=group_id,
            agent_id=agent_id,
            role=role,
            joined_at=datetime.now(timezone.utc),
        )
        self._members.setdefault(group_id, []).append(member)

        if self.db is not None:
            self.db.add(member)
            await self.db.commit()

        return member

    async def remove_member(
        self,
        group_id: uuid.UUID,
        agent_id: uuid.UUID,
    ) -> bool:
        """Remove a member from a group.

        Args:
            group_id: UUID of the target group.
            agent_id: UUID of the agent to remove.

        Returns:
            True if the member was removed, False if not found.
        """
        if group_id not in self._members:
            return False

        members = self._members[group_id]
        for i, member in enumerate(members):
            if member.agent_id == agent_id:
                members.pop(i)
                if self.db is not None:
                    await self.db.delete(member)
                    await self.db.commit()
                return True

        return False

    async def send_group_message(
        self,
        group_id: uuid.UUID,
        sender_agent_id: uuid.UUID,
        content: str,
        message_type: str = "notification",
        priority: str = "normal",
        metadata: Optional[dict[str, Any]] = None,
    ) -> list[Message]:
        """Broadcast a message to all members of a group.

        Creates a message for each group member (excluding the sender)
        with the group_id set for context.

        Args:
            group_id: UUID of the target group.
            sender_agent_id: UUID of the sending agent.
            content: Message body text.
            message_type: Type of message. Defaults to 'notification'.
            priority: Message priority. Defaults to 'normal'.
            metadata: Optional metadata attached to messages.

        Returns:
            List of Message objects sent to group members.
        """
        group = self._groups.get(group_id)
        if group is None:
            return []

        members = self._members.get(group_id, [])
        messages: list[Message] = []

        for member in members:
            if member.agent_id == sender_agent_id:
                continue
            msg = Message(
                id=uuid.uuid4(),
                company_id=group.company_id,
                sender_agent_id=sender_agent_id,
                recipient_agent_id=member.agent_id,
                group_id=group_id,
                message_type=message_type,
                priority=priority,
                content=content,
                msg_metadata=metadata,
                correlation_id=str(uuid.uuid4()),
                delivered=True,
                delivery_route="team",
                created_at=datetime.now(timezone.utc),
                updated_at=None,
            )
            messages.append(msg)

        self._messages.setdefault(group_id, []).extend(messages)

        if self.db is not None:
            for msg in messages:
                self.db.add(msg)
            await self.db.commit()

        return messages

    async def mention_agent(
        self,
        group_id: uuid.UUID,
        sender_agent_id: uuid.UUID,
        target_agent_id: uuid.UUID,
        content: str,
    ) -> Optional[Message]:
        """Send a targeted message to a specific agent within a group context.

        The message is directed to a single agent but retains the group_id
        for context, similar to an @mention in a chat.

        Args:
            group_id: UUID of the group context.
            sender_agent_id: UUID of the sending agent.
            target_agent_id: UUID of the agent being mentioned.
            content: Message body text (typically containing the mention).

        Returns:
            The created Message, or None if the group does not exist.
        """
        group = self._groups.get(group_id)
        if group is None:
            return None

        msg = Message(
            id=uuid.uuid4(),
            company_id=group.company_id,
            sender_agent_id=sender_agent_id,
            recipient_agent_id=target_agent_id,
            group_id=group_id,
            message_type="notification",
            priority="normal",
            content=content,
            msg_metadata={"mention": True, "target_agent_id": str(target_agent_id)},
            correlation_id=str(uuid.uuid4()),
            delivered=True,
            delivery_route="direct",
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        self._messages.setdefault(group_id, []).append(msg)

        if self.db is not None:
            self.db.add(msg)
            await self.db.commit()

        return msg

    def stage_handoff(
        self,
        group_id: uuid.UUID,
        from_agent_id: uuid.UUID,
        to_agent_id: uuid.UUID,
        task_context: str,
        correlation_id: Optional[str] = None,
        mention_targets: Optional[list[uuid.UUID]] = None,
    ) -> Optional[HandoffIntent]:
        """Resolve a handoff and freeze it into an immutable delivery intent.

        Mention targets are staged here, then frozen alongside the rest of the
        intent so delivery applies exactly what was decided. The handoff graph
        is cycle-guarded: handing a task back to an agent that already held it
        in this group is refused.

        Args:
            group_id: UUID of the group context.
            from_agent_id: UUID of the agent delegating the task.
            to_agent_id: UUID of the agent receiving the task.
            task_context: Description of the task being handed off.
            correlation_id: Optional deterministic id; one is generated if absent.
            mention_targets: Optional agents to stage as mention targets.

        Returns:
            The frozen HandoffIntent, or None if the group does not exist.

        Raises:
            CycleGuardError: If the handoff would revisit an earlier holder or
                exceed the cycle guard's depth and repetition limits.
        """
        group = self._groups.get(group_id)
        if group is None:
            return None

        chain = self._handoff_chains.setdefault(group_id, [])
        self._cycle_guard.check_delegation(from_agent_id, to_agent_id, chain)
        if any(to_agent_id in edge for edge in chain):
            raise CycleGuardError(
                from_agent_id,
                to_agent_id,
                f"Agent {to_agent_id} already held this handoff in group {group_id}",
            )

        targets = list(mention_targets or [])
        return HandoffIntent(
            group_id=group_id,
            company_id=group.company_id,
            from_agent_id=from_agent_id,
            to_agent_id=to_agent_id,
            task_context=task_context,
            correlation_id=correlation_id or str(uuid.uuid4()),
            metadata=MappingProxyType(
                {
                    "handoff": True,
                    "from_agent_id": str(from_agent_id),
                    "to_agent_id": str(to_agent_id),
                    "mention_targets": [str(t) for t in targets],
                }
            ),
        )

    async def deliver_handoff(self, intent: HandoffIntent) -> Message:
        """Apply a frozen handoff intent inside the delivery transaction.

        Delivery is idempotent on the intent's correlation_id, so a retried
        delivery resolves to the message already written.

        Args:
            intent: The frozen HandoffIntent to deliver.

        Returns:
            The delivered handoff Message.
        """
        existing = self._delivered_handoffs.get(intent.correlation_id)
        if existing is not None:
            return existing

        msg = Message(
            id=uuid.uuid4(),
            company_id=intent.company_id,
            sender_agent_id=intent.from_agent_id,
            recipient_agent_id=intent.to_agent_id,
            group_id=intent.group_id,
            message_type="handoff",
            priority="urgent",
            content=intent.task_context,
            msg_metadata=dict(intent.metadata),
            correlation_id=intent.correlation_id,
            delivered=True,
            delivery_route="direct",
            created_at=datetime.now(timezone.utc),
            updated_at=None,
        )

        self._messages.setdefault(intent.group_id, []).append(msg)
        self._delivered_handoffs[intent.correlation_id] = msg
        self._handoff_chains.setdefault(intent.group_id, []).append(
            (intent.from_agent_id, intent.to_agent_id)
        )

        if self.db is not None:
            self.db.add(msg)
            await self.db.commit()

        return msg

    async def handoff_in_group(
        self,
        group_id: uuid.UUID,
        from_agent_id: uuid.UUID,
        to_agent_id: uuid.UUID,
        task_context: str,
        correlation_id: Optional[str] = None,
        mention_targets: Optional[list[uuid.UUID]] = None,
    ) -> Optional[Message]:
        """Delegate a task from one agent to another within a group.

        Stages and freezes the delivery intent, then applies it.

        Args:
            group_id: UUID of the group context.
            from_agent_id: UUID of the agent delegating the task.
            to_agent_id: UUID of the agent receiving the task.
            task_context: Description of the task being handed off.
            correlation_id: Optional deterministic id for idempotent delivery.
            mention_targets: Optional agents to stage as mention targets.

        Returns:
            The created handoff Message, or None if the group does not exist.

        Raises:
            CycleGuardError: If the handoff graph would cycle.
        """
        intent = self.stage_handoff(
            group_id,
            from_agent_id,
            to_agent_id,
            task_context,
            correlation_id=correlation_id,
            mention_targets=mention_targets,
        )
        if intent is None:
            return None
        return await self.deliver_handoff(intent)

    async def get_group_history(
        self,
        group_id: uuid.UUID,
        limit: int = 50,
    ) -> list[Message]:
        """Retrieve message history for a group.

        Returns messages ordered by creation time (most recent first).

        Args:
            group_id: UUID of the group.
            limit: Maximum number of messages to return. Defaults to 50.

        Returns:
            List of Message objects for the group.
        """
        messages = self._messages.get(group_id, [])
        sorted_msgs = sorted(messages, key=lambda m: m.created_at, reverse=True)
        return sorted_msgs[:limit]

    def get_group(self, group_id: uuid.UUID) -> Optional[Group]:
        """Retrieve a group by its ID.

        Args:
            group_id: UUID of the group.

        Returns:
            The Group object, or None if not found.
        """
        return self._groups.get(group_id)

    def get_members(self, group_id: uuid.UUID) -> list[GroupMember]:
        """Retrieve all members of a group.

        Args:
            group_id: UUID of the group.

        Returns:
            List of GroupMember objects.
        """
        return self._members.get(group_id, [])
