"""Hive Manager - file-based multi-agent coordination layer.

Directory layout:
  <hive_root>/
    registry.json          # Agent metadata roster
    board.md               # Shared blackboard
    log.jsonl              # Append-only event log
    agents/<id>/
      identity.md          # Agent role/mission
      memory.md            # Agent long-term memory
      inbox/               # Pending messages TO this agent
      inbox/.done/         # Processed messages (audit trail)
      outbox/              # Outgoing messages FROM this agent
      outbox/.sent/        # Delivered messages
      cursor.json          # Agent state cursor
"""

import json
import time
from pathlib import Path
from typing import Optional

from nexus.communication.hive_protocol import AgentStatus, HiveAgentMeta, HiveMessage


class HiveManager:
    """File-based multi-agent coordination layer."""

    def __init__(self, root: Path) -> None:
        """Initialize with the hive root directory path."""
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
        # Create registry.json if not present
        reg_path = self._root / "registry.json"
        if not reg_path.exists():
            reg_path.write_text(json.dumps({"agents": {}}, indent=2))
        # Create board.md if not present
        board_path = self._root / "board.md"
        if not board_path.exists():
            board_path.write_text("# Shared Blackboard\n")
        # Create log.jsonl if not present
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

    def register_agent(self, meta: HiveAgentMeta) -> None:
        """Register an agent and create its workspace directories."""
        # Update registry.json
        registry = self._read_registry()
        registry["agents"][meta.id] = meta.model_dump(mode="json")
        self._write_registry(registry)

        # Create agents/<id>/ with subdirs
        agent_dir = self._root / "agents" / meta.id
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "inbox").mkdir(exist_ok=True)
        (agent_dir / "inbox" / ".done").mkdir(exist_ok=True)
        (agent_dir / "outbox").mkdir(exist_ok=True)
        (agent_dir / "outbox" / ".sent").mkdir(exist_ok=True)

        # Create default files
        identity_path = agent_dir / "identity.md"
        if not identity_path.exists():
            identity_path.write_text(f"# {meta.name}\n\nRole: {meta.role or 'unspecified'}\n")
        memory_path = agent_dir / "memory.md"
        if not memory_path.exists():
            memory_path.write_text("# Memory\n")
        cursor_path = agent_dir / "cursor.json"
        if not cursor_path.exists():
            cursor_path.write_text(json.dumps({"last_processed": 0}, indent=2))

    def unregister_agent(self, agent_id: str, archive: bool = True) -> None:
        """Unregister (archive) an agent. Does not delete files."""
        registry = self._read_registry()
        if agent_id in registry["agents"]:
            if archive:
                registry["agents"][agent_id]["archived"] = True
            else:
                del registry["agents"][agent_id]
            self._write_registry(registry)

    def get_registry(self) -> dict[str, HiveAgentMeta]:
        """Return all registered agents."""
        registry = self._read_registry()
        result: dict[str, HiveAgentMeta] = {}
        for agent_id, data in registry["agents"].items():
            result[agent_id] = HiveAgentMeta(**data)
        return result

    def get_agent(self, agent_id: str) -> Optional[HiveAgentMeta]:
        """Look up a single agent by ID."""
        registry = self._read_registry()
        data = registry["agents"].get(agent_id)
        if data is None:
            return None
        return HiveAgentMeta(**data)

    def update_status(self, agent_id: str, status: AgentStatus) -> None:
        """Update an agent's status in the registry."""
        registry = self._read_registry()
        if agent_id in registry["agents"]:
            registry["agents"][agent_id]["status"] = status.value
            registry["agents"][agent_id]["last_seen"] = time.time()
            self._write_registry(registry)

    def send_message(self, msg: HiveMessage) -> None:
        """Write a message to the sender's outbox directory."""
        agent_dir = self._root / "agents" / msg.from_agent
        outbox = agent_dir / "outbox"
        outbox.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}-{msg.id}.json"
        filepath = outbox / filename
        filepath.write_text(json.dumps(msg.model_dump(mode="json"), indent=2))

    def deliver_to_inbox(self, agent_id: str, msg: HiveMessage) -> None:
        """Write a message to a recipient's inbox directory."""
        agent_dir = self._root / "agents" / agent_id
        inbox = agent_dir / "inbox"
        inbox.mkdir(parents=True, exist_ok=True)

        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}-{msg.id}.json"
        filepath = inbox / filename
        filepath.write_text(json.dumps(msg.model_dump(mode="json"), indent=2))

    def get_inbox(self, agent_id: str) -> list[HiveMessage]:
        """Read all pending messages from an agent's inbox."""
        inbox = self._root / "agents" / agent_id / "inbox"
        if not inbox.exists():
            return []

        messages: list[HiveMessage] = []
        for filepath in sorted(inbox.glob("*.json")):
            data = json.loads(filepath.read_text())
            messages.append(HiveMessage(**data))
        return messages

    def mark_processed(self, agent_id: str, msg_id: str) -> None:
        """Move a message from inbox/ to inbox/.done/."""
        inbox = self._root / "agents" / agent_id / "inbox"
        done_dir = inbox / ".done"
        done_dir.mkdir(exist_ok=True)

        for filepath in inbox.glob("*.json"):
            if msg_id in filepath.name:
                dest = done_dir / filepath.name
                filepath.rename(dest)
                return

    def get_blackboard(self) -> str:
        """Read the shared blackboard content."""
        board_path = self._root / "board.md"
        return board_path.read_text()

    def update_blackboard(self, content: str) -> None:
        """Update the shared blackboard content."""
        board_path = self._root / "board.md"
        board_path.write_text(content)

    def append_log(self, event: dict) -> None:
        """Append an event to the JSONL log."""
        log_path = self._root / "log.jsonl"
        with log_path.open("a") as f:
            f.write(json.dumps(event) + "\n")

    def get_log(self, limit: int = 100) -> list[dict]:
        """Read the most recent log entries."""
        log_path = self._root / "log.jsonl"
        if not log_path.exists():
            return []

        lines = log_path.read_text().strip().splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
        return entries[-limit:]
