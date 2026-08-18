"""Group communication manager for multi-agent conversations and handoffs.

Provides group creation, membership management, message broadcasting within
groups, agent mentions, and task handoffs between group members.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from nexus.models.communication import Group, GroupMember, Message


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
                metadata=metadata,
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
            metadata={"mention": True, "target_agent_id": str(target_agent_id)},
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

    async def handoff_in_group(
        self,
        group_id: uuid.UUID,
        from_agent_id: uuid.UUID,
        to_agent_id: uuid.UUID,
        task_context: str,
    ) -> Optional[Message]:
        """Delegate a task from one agent to another within a group.

        Creates a handoff message that transfers responsibility for a task
        from one agent to another, maintaining the group context.

        Args:
            group_id: UUID of the group context.
            from_agent_id: UUID of the agent delegating the task.
            to_agent_id: UUID of the agent receiving the task.
            task_context: Description of the task being handed off.

        Returns:
            The created handoff Message, or None if the group does not exist.
        """
        group = self._groups.get(group_id)
        if group is None:
            return None

        msg = Message(
            id=uuid.uuid4(),
            company_id=group.company_id,
            sender_agent_id=from_agent_id,
            recipient_agent_id=to_agent_id,
            group_id=group_id,
            message_type="handoff",
            priority="urgent",
            content=task_context,
            metadata={
                "handoff": True,
                "from_agent_id": str(from_agent_id),
                "to_agent_id": str(to_agent_id),
            },
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
