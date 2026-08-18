"""Communication module for inter-agent messaging, group conversations, channels, and events.

This module provides the full communication infrastructure for the NEXUS platform:
- A2AProtocol: Agent-to-agent messaging with at-least-once delivery
- GroupManager: Group conversations, broadcasts, and handoffs
- ChannelRouter: External channel integration (Slack, Discord, Webhooks)
- EventBus: Pub/sub event system with async/sync handler support
"""

from nexus.communication.a2a import A2AProtocol
from nexus.communication.channels import ChannelRouter
from nexus.communication.event_bus import EventBus
from nexus.communication.group import GroupManager

__all__ = [
    "A2AProtocol",
    "GroupManager",
    "ChannelRouter",
    "EventBus",
]
