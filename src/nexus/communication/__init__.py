"""Communication module for inter-agent messaging, group conversations, channels, and events.

This module provides the full communication infrastructure for the NEXUS platform:
- A2AProtocol: Agent-to-agent messaging with at-least-once delivery
- A2ARouter: Structured communication modes (notify, consult, delegate)
- A2AMessage: Typed message dataclass for A2A routing
- CommunicationMode: Enum for communication modes
- GroupManager: Group conversations, broadcasts, and handoffs
- ChannelRouter: External channel integration (Slack, Discord, Webhooks)
- EventBus: Pub/sub event system with async/sync handler support
- HiveMessage: FIPA-lite message for file-based multi-agent coordination
- HiveManager: File-based agent workspace management
- HiveRouter: Message routing from outbox to inbox directories
- HiveTask: Kanban-style task ledger for agent coordination
"""

from nexus.communication.a2a import A2AProtocol
from nexus.communication.a2a_router import (
    A2AMessage,
    A2ARouter,
    CommunicationMode,
    correlation_id_for,
    execution_id_for,
)
from nexus.communication.channels import ChannelRouter
from nexus.communication.event_bus import EventBus
from nexus.communication.group import GroupManager, HandoffIntent
from nexus.communication.hive_manager import HiveManager
from nexus.communication.hive_protocol import (
    HOP_CAP,
    REPLY_OBLIGATING_ACTS,
    AgentStatus,
    HiveAgentMeta,
    HiveMessage,
    MessageAct,
    requires_reply_for_act,
)
from nexus.communication.hive_router import HiveRouter
from nexus.communication.permits import DEFAULT_SUBAGENT_CAP, SubagentPermits
from nexus.communication.hive_task import HiveTask, TaskStatus

__all__ = [
    "A2AProtocol",
    "A2ARouter",
    "A2AMessage",
    "CommunicationMode",
    "GroupManager",
    "HandoffIntent",
    "SubagentPermits",
    "DEFAULT_SUBAGENT_CAP",
    "correlation_id_for",
    "execution_id_for",
    "ChannelRouter",
    "EventBus",
    "HiveMessage",
    "MessageAct",
    "HiveAgentMeta",
    "AgentStatus",
    "HiveManager",
    "HiveRouter",
    "HiveTask",
    "TaskStatus",
    "HOP_CAP",
    "REPLY_OBLIGATING_ACTS",
    "requires_reply_for_act",
]
