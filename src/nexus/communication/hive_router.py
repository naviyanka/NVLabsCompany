"""Hive Router - drains outbox messages into recipient inboxes."""

import json
import time
from pathlib import Path

from nexus.communication.hive_manager import HiveManager
from nexus.communication.hive_protocol import HOP_CAP, HiveMessage


class HiveRouter:
    """Routes messages from agent outboxes to recipient inboxes."""

    def __init__(self, manager: HiveManager) -> None:
        """Initialize with a HiveManager instance."""
        self._manager = manager

    def route(self) -> list[tuple[HiveMessage, list[str]]]:
        """Drain all outbox directories and deliver messages.

        For each message:
        - to_agent = specific agent_id: deliver to that agent's inbox
        - to_agent = "broadcast": fan out to all active non-archived agents (except sender)
        - to_agent = "god": deliver to the god agent from registry
        - to_agent = "human": deliver to god agent (human's proxy)

        Enforces HOP_CAP: messages at/above 12 hops are NOT delivered (livelock prevention).
        Moves delivered messages from outbox/ to outbox/.sent/.
        Appends delivery events to the log.

        Returns list of (message, recipient_ids) tuples.
        """
        deliveries: list[tuple[HiveMessage, list[str]]] = []
        agents_dir = self._manager.root / "agents"

        if not agents_dir.exists():
            return deliveries

        registry = self._manager.get_registry()

        for agent_dir in agents_dir.iterdir():
            if not agent_dir.is_dir():
                continue
            outbox = agent_dir / "outbox"
            if not outbox.exists():
                continue

            for msg_file in sorted(outbox.glob("*.json")):
                data = json.loads(msg_file.read_text())
                msg = HiveMessage(**data)

                # Enforce hop cap
                if msg.hops >= HOP_CAP:
                    self._manager.append_log({
                        "event": "livelock_prevented",
                        "message_id": msg.id,
                        "from_agent": msg.from_agent,
                        "to_agent": msg.to_agent,
                        "hops": msg.hops,
                        "timestamp": time.time(),
                    })
                    # Move to .sent even though not delivered (prevent re-processing)
                    sent_dir = outbox / ".sent"
                    sent_dir.mkdir(exist_ok=True)
                    msg_file.rename(sent_dir / msg_file.name)
                    continue

                # Determine recipients
                recipients = self._resolve_recipients(msg, registry)

                # Deliver to each recipient's inbox
                for recipient_id in recipients:
                    self._manager.deliver_to_inbox(recipient_id, msg)

                # Move from outbox to outbox/.sent
                sent_dir = outbox / ".sent"
                sent_dir.mkdir(exist_ok=True)
                msg_file.rename(sent_dir / msg_file.name)

                # Log the delivery event
                self._manager.append_log({
                    "event": "message_delivered",
                    "message_id": msg.id,
                    "from_agent": msg.from_agent,
                    "to_agent": msg.to_agent,
                    "recipients": recipients,
                    "hops": msg.hops,
                    "timestamp": time.time(),
                })

                deliveries.append((msg, recipients))

        return deliveries

    def _resolve_recipients(
        self, msg: HiveMessage, registry: dict
    ) -> list[str]:
        """Resolve the target recipients for a message."""
        if msg.to_agent == "broadcast":
            # Fan out to all active non-archived agents except sender
            return [
                agent_id
                for agent_id, meta in registry.items()
                if not meta.archived and agent_id != msg.from_agent
            ]
        elif msg.to_agent in ("god", "human"):
            # Deliver to the god agent
            god_agents = [
                agent_id
                for agent_id, meta in registry.items()
                if meta.is_god and not meta.archived
            ]
            return god_agents
        else:
            # Deliver to specific agent
            if msg.to_agent in registry:
                return [msg.to_agent]
            return []
