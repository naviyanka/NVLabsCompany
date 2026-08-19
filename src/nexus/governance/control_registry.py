"""Control Registry - per-agent operator control state.

Ported from munder-difflin/src/main/control.ts. Holds per-agent control state
that hook servers read when deciding what to return from a hook. This is how
the floor exerts control WITHOUT typing into the PTY.

- pause / gate_tool: tool calls return deny decisions
- steer: inject guidance into agent context via FIFO queue
- halt: graceful stop at next hook boundary
- resume: clear pause + halt (keeps gates)
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# Maximum bytes for a single steer entry (10 KB).
MAX_STEER_BYTES: int = 10_000


@dataclass
class AgentControl:
    """Internal per-agent control state."""

    paused: bool = False
    halted: bool = False
    auto_delivery_paused: bool = False
    gated_tools: set[str] = field(default_factory=set)
    steer_queue: list[str] = field(default_factory=list)


@dataclass
class AgentControlSnapshot:
    """Public read-only snapshot of an agent's control state."""

    paused: bool
    halted: bool
    auto_delivery_paused: bool
    gated_tools: list[str]
    pending_steers: int


class ControlRegistry:
    """Per-agent operator control registry.

    Provides operator actions (pause, gate_tool, steer, halt, resume) and
    read methods (tool_decision, take_steer, snapshot, should_halt,
    is_auto_delivery_paused) for hook-based enforcement.
    """

    def __init__(self, persist_path: Path | None = None) -> None:
        """Initialize the registry with an empty agent map.

        Args:
            persist_path: Optional path to a JSON file for persisting state.
                When provided, state is saved after every mutation and loaded
                on init if the file exists. When None, no persistence occurs.
        """
        self._persist_path = persist_path
        self._map: dict[str, AgentControl] = {}
        self._load()

    def _ensure(self, agent_id: str) -> AgentControl:
        """Get or create the control state for an agent."""
        if agent_id not in self._map:
            self._map[agent_id] = AgentControl()
        return self._map[agent_id]

    # ── Persistence ──────────────────────────────────────────────────────────

    def _persist(self) -> None:
        """Atomically write current state to the persist file."""
        if self._persist_path is None:
            return
        data: dict[str, dict] = {}
        for agent_id, ctrl in self._map.items():
            data[agent_id] = {
                "paused": ctrl.paused,
                "halted": ctrl.halted,
                "auto_delivery_paused": ctrl.auto_delivery_paused,
                "gated_tools": sorted(ctrl.gated_tools),
                "steer_queue": ctrl.steer_queue,
            }
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._persist_path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self._persist_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def _load(self) -> None:
        """Load state from the persist file if it exists."""
        if self._persist_path is None or not self._persist_path.exists():
            return
        with open(self._persist_path) as f:
            data: dict[str, dict] = json.load(f)
        for agent_id, ctrl_data in data.items():
            self._map[agent_id] = AgentControl(
                paused=ctrl_data["paused"],
                halted=ctrl_data["halted"],
                auto_delivery_paused=ctrl_data["auto_delivery_paused"],
                gated_tools=set(ctrl_data["gated_tools"]),
                steer_queue=ctrl_data["steer_queue"],
            )

    # ── Operator actions ─────────────────────────────────────────────────────

    def pause(self, agent_id: str, on: bool) -> None:
        """Set or clear the paused flag for an agent."""
        self._ensure(agent_id).paused = on
        self._persist()

    def pause_auto_delivery(self, agent_id: str, on: bool) -> None:
        """Set or clear the auto-delivery pause flag for an agent."""
        self._ensure(agent_id).auto_delivery_paused = on
        self._persist()

    def gate_tool(self, agent_id: str, tool: str, on: bool) -> None:
        """Add or remove a tool from the gated set for an agent."""
        ctrl = self._ensure(agent_id)
        if on:
            ctrl.gated_tools.add(tool)
        else:
            ctrl.gated_tools.discard(tool)
        self._persist()

    def steer(self, agent_id: str, text: str) -> None:
        """Enqueue a guidance note for the agent (max 10KB, trimmed)."""
        trimmed = text.strip()
        if trimmed:
            self._ensure(agent_id).steer_queue.append(trimmed[:MAX_STEER_BYTES])
            self._persist()

    def halt(self, agent_id: str) -> None:
        """Request a graceful stop at the next hook boundary."""
        self._ensure(agent_id).halted = True
        self._persist()

    def resume(self, agent_id: str) -> None:
        """Clear pause and halt flags (keeps gates intact)."""
        ctrl = self._ensure(agent_id)
        ctrl.paused = False
        ctrl.halted = False
        self._persist()

    def clear_steers(self, agent_id: str) -> None:
        """Drop all queued-but-undelivered steer notes for an agent."""
        ctrl = self._map.get(agent_id)
        if ctrl:
            ctrl.steer_queue.clear()
            self._persist()

    # ── Read methods (used by hook server) ───────────────────────────────────

    def tool_decision(self, agent_id: str, tool: str) -> tuple[bool, str | None]:
        """Determine if a tool call should be denied.

        Returns a tuple of (deny, reason). For unknown agents, returns
        (False, None).
        """
        ctrl = self._map.get(agent_id)
        if ctrl is None:
            return (False, None)
        if ctrl.paused:
            return (True, "Paused by operator - resume from the floor to continue.")
        if tool and ctrl.gated_tools and tool in ctrl.gated_tools:
            return (True, f"Tool {tool} is gated by the operator.")
        return (False, None)

    def take_steer(self, agent_id: str) -> str | None:
        """Dequeue one pending steer note for delivery, or None."""
        ctrl = self._map.get(agent_id)
        if ctrl and ctrl.steer_queue:
            return ctrl.steer_queue.pop(0)
        return None

    def snapshot(self, agent_id: str) -> AgentControlSnapshot:
        """Return a read-only snapshot of the agent's control state."""
        ctrl = self._map.get(agent_id)
        return AgentControlSnapshot(
            paused=ctrl.paused if ctrl else False,
            halted=ctrl.halted if ctrl else False,
            auto_delivery_paused=ctrl.auto_delivery_paused if ctrl else False,
            gated_tools=sorted(ctrl.gated_tools) if ctrl else [],
            pending_steers=len(ctrl.steer_queue) if ctrl else 0,
        )

    def should_halt(self, agent_id: str) -> bool:
        """Check if the agent should halt at the next boundary."""
        ctrl = self._map.get(agent_id)
        return ctrl.halted if ctrl else False

    def is_auto_delivery_paused(self, agent_id: str) -> bool:
        """Check if auto-delivery is paused for the agent."""
        ctrl = self._map.get(agent_id)
        return ctrl.auto_delivery_paused if ctrl else False
