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

from dataclasses import dataclass, field

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

    def __init__(self) -> None:
        """Initialize the registry with an empty agent map."""
        self._map: dict[str, AgentControl] = {}

    def _ensure(self, agent_id: str) -> AgentControl:
        """Get or create the control state for an agent."""
        if agent_id not in self._map:
            self._map[agent_id] = AgentControl()
        return self._map[agent_id]

    # ── Operator actions ─────────────────────────────────────────────────────

    def pause(self, agent_id: str, on: bool) -> None:
        """Set or clear the paused flag for an agent."""
        self._ensure(agent_id).paused = on

    def pause_auto_delivery(self, agent_id: str, on: bool) -> None:
        """Set or clear the auto-delivery pause flag for an agent."""
        self._ensure(agent_id).auto_delivery_paused = on

    def gate_tool(self, agent_id: str, tool: str, on: bool) -> None:
        """Add or remove a tool from the gated set for an agent."""
        ctrl = self._ensure(agent_id)
        if on:
            ctrl.gated_tools.add(tool)
        else:
            ctrl.gated_tools.discard(tool)

    def steer(self, agent_id: str, text: str) -> None:
        """Enqueue a guidance note for the agent (max 10KB, trimmed)."""
        trimmed = text.strip()
        if trimmed:
            self._ensure(agent_id).steer_queue.append(trimmed[:MAX_STEER_BYTES])

    def halt(self, agent_id: str) -> None:
        """Request a graceful stop at the next hook boundary."""
        self._ensure(agent_id).halted = True

    def resume(self, agent_id: str) -> None:
        """Clear pause and halt flags (keeps gates intact)."""
        ctrl = self._ensure(agent_id)
        ctrl.paused = False
        ctrl.halted = False

    def clear_steers(self, agent_id: str) -> None:
        """Drop all queued-but-undelivered steer notes for an agent."""
        ctrl = self._map.get(agent_id)
        if ctrl:
            ctrl.steer_queue.clear()

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
