"""Pluggable backends for HiveManager multi-agent coordination.

Defines a HiveBackend Protocol and two implementations:
- FileHiveBackend: Extracts the file-based logic from HiveManager.
- RedisHiveBackend: Uses Redis Streams for distributed messaging.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Protocol, runtime_checkable

from nexus.communication.hive_protocol import AgentStatus, HiveAgentMeta, HiveMessage

logger = logging.getLogger(__name__)


@runtime_checkable
class HiveBackend(Protocol):
    """Protocol defining the pluggable hive backend interface.

    All methods are async to support both file-based and Redis-based
    implementations transparently without sync/async impedance mismatch.
    """

    async def send_message(self, msg: HiveMessage) -> None:
        """Write a message to the sender's outbox.

        Args:
            msg: The message to send.
        """
        ...

    async def deliver_to_inbox(self, agent_id: str, msg: HiveMessage) -> None:
        """Deliver a message to a recipient's inbox.

        Args:
            agent_id: The target agent ID.
            msg: The message to deliver.
        """
        ...

    async def get_inbox(self, agent_id: str) -> list[HiveMessage]:
        """Read all pending messages for an agent.

        Args:
            agent_id: The agent whose inbox to read.

        Returns:
            List of pending HiveMessage objects.
        """
        ...

    async def mark_processed(self, agent_id: str, msg_id: str) -> None:
        """Mark a message as processed.

        Args:
            agent_id: The agent that processed the message.
            msg_id: The message ID to mark as done.
        """
        ...

    async def get_registry(self) -> dict[str, HiveAgentMeta]:
        """Return all registered agents.

        Returns:
            Dictionary mapping agent IDs to their metadata.
        """
        ...

    async def register_agent(self, meta: HiveAgentMeta) -> None:
        """Register an agent in the backend.

        Args:
            meta: The agent metadata to register.
        """
        ...

    async def unregister_agent(self, agent_id: str, archive: bool = True) -> None:
        """Unregister (or archive) an agent.

        Args:
            agent_id: The agent to unregister.
            archive: If True, mark as archived; if False, remove entirely.
        """
        ...

    async def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status.

        Args:
            agent_id: The agent whose status to update.
            status: The new status value.
        """
        ...


class FileHiveBackend:
    """File-based hive backend using the filesystem for state.

    This extracts the original file-based logic from HiveManager into a
    standalone backend implementation that conforms to HiveBackend.
    """

    def __init__(self, root: Path) -> None:
        """Initialize with the hive root directory path.

        Args:
            root: Path to the hive directory structure.
        """
        self._root = root
        self._ensure_structure()

    @property
    def root(self) -> Path:
        """Return the hive root directory path."""
        return self._root

    def _ensure_structure(self) -> None:
        """Create the base hive directory structure if not present."""
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "agents").mkdir(exist_ok=True)
        reg_path = self._root / "registry.json"
        if not reg_path.exists():
            reg_path.write_text(json.dumps({"agents": {}}, indent=2))
        board_path = self._root / "board.md"
        if not board_path.exists():
            board_path.write_text("# Shared Blackboard\n")
        log_path = self._root / "log.jsonl"
        if not log_path.exists():
            log_path.write_text("")

    def _read_registry(self) -> dict:
        """Read the registry.json file."""
        reg_path = self._root / "registry.json"
        return json.loads(reg_path.read_text())

    def _write_registry(self, data: dict) -> None:
        """Write the registry.json file."""
        reg_path = self._root / "registry.json"
        reg_path.write_text(json.dumps(data, indent=2))

    async def send_message(self, msg: HiveMessage) -> None:
        """Write a message to the sender's outbox directory.

        Args:
            msg: The message to send.
        """
        agent_dir = self._root / "agents" / msg.from_agent
        outbox = agent_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}-{msg.id}.json"
        filepath = outbox / filename
        filepath.write_text(json.dumps(msg.model_dump(mode="json"), indent=2))

    async def deliver_to_inbox(self, agent_id: str, msg: HiveMessage) -> None:
        """Write a message to a recipient's inbox directory.

        Args:
            agent_id: The target agent ID.
            msg: The message to deliver.
        """
        agent_dir = self._root / "agents" / agent_id
        inbox = agent_dir / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}-{msg.id}.json"
        filepath = inbox / filename
        filepath.write_text(json.dumps(msg.model_dump(mode="json"), indent=2))

    async def get_inbox(self, agent_id: str) -> list[HiveMessage]:
        """Read all pending messages from an agent's inbox.

        Args:
            agent_id: The agent whose inbox to read.

        Returns:
            List of pending HiveMessage objects.
        """
        inbox = self._root / "agents" / agent_id / "inbox"
        if not inbox.exists():
            return []

        messages: list[HiveMessage] = []
        for filepath in sorted(inbox.glob("*.json")):
            data = json.loads(filepath.read_text())
            messages.append(HiveMessage(**data))
        return messages

    async def mark_processed(self, agent_id: str, msg_id: str) -> None:
        """Move a message from inbox/ to inbox/.done/.

        Args:
            agent_id: The agent that processed the message.
            msg_id: The message ID to mark as done.
        """
        inbox = self._root / "agents" / agent_id / "inbox"
        done_dir = inbox / ".done"
        done_dir.mkdir(exist_ok=True)

        for filepath in inbox.glob("*.json"):
            if msg_id in filepath.name:
                dest = done_dir / filepath.name
                filepath.rename(dest)
                return

    async def get_registry(self) -> dict[str, HiveAgentMeta]:
        """Return all registered agents.

        Returns:
            Dictionary mapping agent IDs to their metadata.
        """
        registry = self._read_registry()
        result: dict[str, HiveAgentMeta] = {}
        for agent_id, data in registry["agents"].items():
            result[agent_id] = HiveAgentMeta(**data)
        return result

    async def register_agent(self, meta: HiveAgentMeta) -> None:
        """Register an agent and create its workspace directories.

        Args:
            meta: The agent metadata to register.
        """
        registry = self._read_registry()
        registry["agents"][meta.id] = meta.model_dump(mode="json")
        self._write_registry(registry)

        agent_dir = self._root / "agents" / meta.id
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "inbox").mkdir(exist_ok=True)
        (agent_dir / "inbox" / ".done").mkdir(exist_ok=True)
        (agent_dir / "outbox").mkdir(exist_ok=True)
        (agent_dir / "outbox" / ".sent").mkdir(exist_ok=True)

        identity_path = agent_dir / "identity.md"
        if not identity_path.exists():
            identity_path.write_text(
                f"# {meta.name}\n\nRole: {meta.role or 'unspecified'}\n"
            )
        memory_path = agent_dir / "memory.md"
        if not memory_path.exists():
            memory_path.write_text("# Memory\n")
        cursor_path = agent_dir / "cursor.json"
        if not cursor_path.exists():
            cursor_path.write_text(json.dumps({"last_processed": 0}, indent=2))

    async def unregister_agent(self, agent_id: str, archive: bool = True) -> None:
        """Unregister (archive) an agent. Does not delete files.

        Args:
            agent_id: The agent to unregister.
            archive: If True, mark as archived; if False, remove from registry.
        """
        registry = self._read_registry()
        if agent_id in registry["agents"]:
            if archive:
                registry["agents"][agent_id]["archived"] = True
            else:
                del registry["agents"][agent_id]
            self._write_registry(registry)

    async def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status in the registry.

        Args:
            agent_id: The agent whose status to update.
            status: The new status value.
        """
        registry = self._read_registry()
        if agent_id in registry["agents"]:
            registry["agents"][agent_id]["status"] = status.value
            registry["agents"][agent_id]["last_seen"] = time.time()
            self._write_registry(registry)


class RedisHiveBackend:
    """Redis Streams-based hive backend for distributed messaging.

    Uses Redis Streams for message delivery and Redis hashes for the
    agent registry. All methods are natively async, matching the
    HiveBackend protocol.
    """

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "nexus:hive",
        recovery_cooldown_seconds: float = 30.0,
    ) -> None:
        """Initialize with a Redis connection URL.

        Args:
            redis_url: Redis connection string (redis://host:port/db).
            key_prefix: Prefix for all Redis keys used by this backend.
            recovery_cooldown_seconds: Seconds to wait before attempting
                recovery after a failure.
        """
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        self._prefix = key_prefix
        self._available = True
        self._recovery_cooldown = recovery_cooldown_seconds
        self._last_failure_time: float = 0.0

    def _inbox_key(self, agent_id: str) -> str:
        """Build the Redis stream key for an agent's inbox."""
        return f"{self._prefix}:inbox:{agent_id}"

    def _outbox_key(self, agent_id: str) -> str:
        """Build the Redis stream key for an agent's outbox."""
        return f"{self._prefix}:outbox:{agent_id}"

    def _registry_key(self) -> str:
        """Build the Redis hash key for the agent registry."""
        return f"{self._prefix}:registry"

    async def _check_recovery(self) -> bool:
        """Check whether enough time has passed to attempt recovery.

        If the backend is unavailable and the cooldown has elapsed, tries
        a PING to re-enable operations.

        Returns:
            True if the backend is available (or recovered), False otherwise.
        """
        if self._available:
            return True

        elapsed = time.monotonic() - self._last_failure_time
        if elapsed < self._recovery_cooldown:
            return False

        # Attempt recovery via health check
        try:
            result = await self._redis.ping()
            if result:
                self._available = True
                logger.info("Redis hive backend recovered after cooldown")
                return True
        except Exception:
            # Reset the failure timer so we wait another cooldown period
            self._last_failure_time = time.monotonic()
        return False

    def _mark_unavailable(self) -> None:
        """Mark the backend as unavailable and record the failure time."""
        self._available = False
        self._last_failure_time = time.monotonic()

    async def send_message(self, msg: HiveMessage) -> None:
        """Write a message to the sender's outbox stream.

        Args:
            msg: The message to send.
        """
        if not await self._check_recovery():
            return
        try:
            key = self._outbox_key(msg.from_agent)
            data = {"payload": json.dumps(msg.model_dump(mode="json"))}
            await self._redis.xadd(key, data)
        except Exception as exc:
            logger.warning("Redis hive send failed: %s", exc)
            self._mark_unavailable()

    async def deliver_to_inbox(self, agent_id: str, msg: HiveMessage) -> None:
        """Deliver a message to a recipient's inbox stream.

        Args:
            agent_id: The target agent ID.
            msg: The message to deliver.
        """
        if not await self._check_recovery():
            return
        try:
            key = self._inbox_key(agent_id)
            data = {"payload": json.dumps(msg.model_dump(mode="json"))}
            await self._redis.xadd(key, data)
        except Exception as exc:
            logger.warning("Redis hive deliver failed: %s", exc)
            self._mark_unavailable()

    async def get_inbox(self, agent_id: str) -> list[HiveMessage]:
        """Read pending messages from an agent's inbox stream.

        Args:
            agent_id: The agent whose inbox to read.

        Returns:
            List of pending HiveMessage objects.
        """
        if not await self._check_recovery():
            return []
        try:
            key = self._inbox_key(agent_id)
            entries = await self._redis.xrange(key)
            messages: list[HiveMessage] = []
            for _entry_id, data in entries:
                payload = json.loads(data["payload"])
                messages.append(HiveMessage(**payload))
            return messages
        except Exception as exc:
            logger.warning("Redis hive get_inbox failed: %s", exc)
            self._mark_unavailable()
            return []

    async def mark_processed(self, agent_id: str, msg_id: str) -> None:
        """Mark a message as processed by deleting it from the stream.

        Args:
            agent_id: The agent that processed the message.
            msg_id: The message ID to mark as done.
        """
        if not await self._check_recovery():
            return
        try:
            key = self._inbox_key(agent_id)
            entries = await self._redis.xrange(key)
            for entry_id, data in entries:
                payload = json.loads(data["payload"])
                if payload.get("id") == msg_id:
                    await self._redis.xdel(key, entry_id)
                    return
        except Exception as exc:
            logger.warning("Redis hive mark_processed failed: %s", exc)
            self._mark_unavailable()

    async def get_registry(self) -> dict[str, HiveAgentMeta]:
        """Return all registered agents from Redis hash.

        Returns:
            Dictionary mapping agent IDs to their metadata.
        """
        if not await self._check_recovery():
            return {}
        try:
            key = self._registry_key()
            data = await self._redis.hgetall(key)
            result: dict[str, HiveAgentMeta] = {}
            for agent_id, raw in data.items():
                result[agent_id] = HiveAgentMeta(**json.loads(raw))
            return result
        except Exception as exc:
            logger.warning("Redis hive get_registry failed: %s", exc)
            self._mark_unavailable()
            return {}

    async def register_agent(self, meta: HiveAgentMeta) -> None:
        """Register an agent in Redis.

        Args:
            meta: The agent metadata to register.
        """
        if not await self._check_recovery():
            return
        try:
            key = self._registry_key()
            data = json.dumps(meta.model_dump(mode="json"))
            await self._redis.hset(key, meta.id, data)
        except Exception as exc:
            logger.warning("Redis hive register failed: %s", exc)
            self._mark_unavailable()

    async def unregister_agent(self, agent_id: str, archive: bool = True) -> None:
        """Unregister an agent from Redis.

        Args:
            agent_id: The agent to unregister.
            archive: If True, mark as archived; if False, remove entirely.
        """
        if not await self._check_recovery():
            return
        try:
            key = self._registry_key()
            if archive:
                raw = await self._redis.hget(key, agent_id)
                if raw:
                    data = json.loads(raw)
                    data["archived"] = True
                    await self._redis.hset(key, agent_id, json.dumps(data))
            else:
                await self._redis.hdel(key, agent_id)
        except Exception as exc:
            logger.warning("Redis hive unregister failed: %s", exc)
            self._mark_unavailable()

    async def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status in Redis.

        Args:
            agent_id: The agent whose status to update.
            status: The new status value.
        """
        if not await self._check_recovery():
            return
        try:
            key = self._registry_key()
            raw = await self._redis.hget(key, agent_id)
            if raw:
                data = json.loads(raw)
                data["status"] = status.value
                data["last_seen"] = time.time()
                await self._redis.hset(key, agent_id, json.dumps(data))
        except Exception as exc:
            logger.warning("Redis hive update_status failed: %s", exc)
            self._mark_unavailable()
