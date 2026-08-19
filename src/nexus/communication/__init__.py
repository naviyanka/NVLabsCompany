"""Communication module for inter-agent messaging, group conversations, channels, and events.

This module provides the full communication infrastructure for the NEXUS platform:
- A2AProtocol: Agent-to-agent messaging with at-least-once delivery
- A2ARouter: Structured communication modes (notify, consult, delegate)
- A2AMessage: Typed message dataclass for A2A routing
- CommunicationMode: Enum for communication modes
- GroupManager: Group conversations, broadcasts, and handoffs
- ChannelRouter: External channel integration (Slack, Discord, Webhooks)
- EventBus: Pub/sub event system with async/sync handler support
"""

from nexus.communication.a2a import A2AProtocol
from nexus.communication.a2a_router import A2AMessage, A2ARouter, CommunicationMode
from nexus.communication.channels import ChannelRouter
from nexus.communication.event_bus import EventBus
from nexus.communication.group import GroupManager

__all__ = [
    "A2AProtocol",
    "A2ARouter",
    "A2AMessage",
    "CommunicationMode",
    "GroupManager",
    "ChannelRouter",
    "EventBus",
]
