"""Advanced circuit breaker with velocity, loop, cost, and no-progress detection.

Implements a multi-signal circuit breaker with a four-level escalation ladder
(healthy -> steering -> constrained -> stopped). Ported from the TypeScript
reference in munder-difflin/src/main/breaker.ts.

The breaker owns POLICY only - trip conditions and the escalation ladder.
It has no side effects: it reads signals and returns decisions. The caller
performs enforcement (corrective messages, notifications, kill+archive).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from nexus.governance.breaker_types import (
    AgentUsageSample,
    BreakerAction,
    BreakerConfig,
    BreakerDecision,
    BreakerInput,
    BreakerLevel,
    BreakerState,
)

# ── Constants ────────────────────────────────────────────────────────────────

COMPACT_GRACE_MS: float = 5 * 60_000
"""Safety cap on the PreCompact exemption (5 minutes)."""

POST_COMPACT_GRACE_MS: float = 90_000
"""Trailing grace after PostCompact (90 seconds)."""

PROGRESS_TOOL_WINDOW_MS: float = 300_000
"""How recent a distinct tool call must be to count as progress (5 minutes)."""

NO_PROGRESS_BEATS: int = 2
"""Consecutive tripping beats needed before the no-progress arm fires."""


@dataclass
class _AgentBreakerState:
    """Internal per-agent tracking state."""

    level: BreakerLevel = BreakerLevel.HEALTHY
    reason: str = ""
    last_sample: AgentUsageSample | None = None
    repeat_key: str | None = None
    repeat_count: int = 0
    error_count: int = 0
    compacting_until: float = 0
    last_distinct_tool_at: float = 0
    no_progress_beats: int = 0


def _tokens_of(sample: AgentUsageSample | None) -> int:
    """Total tokens in a cumulative sample (all kinds), 0 when unknown."""
    if sample is None:
        return 0
    return sample.input + sample.output + sample.cache_read + sample.cache_creation


def _action_for(level: BreakerLevel) -> BreakerAction:
    """Map a breaker level to the corresponding action."""
    if level == BreakerLevel.STEERING:
        return BreakerAction.STEER
    if level == BreakerLevel.CONSTRAINED:
        return BreakerAction.CONSTRAIN
    if level == BreakerLevel.STOPPED:
        return BreakerAction.STOP
    return BreakerAction.NONE


class AdvancedCircuitBreaker:
    """Multi-signal circuit breaker with escalation ladder.

    Evaluates six trip conditions per beat:
    1. Repeated identical tool calls (loop detection)
    2. Error storm (consecutive api errors)
    3. Per-agent token cap
    4. Floor-wide cost cap (blames top spender)
    5. Floor-wide token cap (blames top spender)
    6. Token velocity spike (with compaction exemption)
    7. No-progress detection (within velocity check, debounced)

    Escalation is one level per tick (never jumps). De-escalation is also
    one level per healthy tick. The ceiling is CONSTRAINED unless hard_stop
    is enabled, in which case STOPPED is reachable.
    """

    def __init__(self, config_getter: Callable[[], BreakerConfig]) -> None:
        """Initialize the circuit breaker.

        Args:
            config_getter: Callable that returns current BreakerConfig.
        """
        self._config_getter = config_getter
        self._agents: dict[str, _AgentBreakerState] = {}

    def _get_config(self) -> BreakerConfig:
        """Retrieve the current configuration."""
        cfg = self._config_getter()
        if cfg is None:
            return BreakerConfig()
        return cfg

    def _get_state(self, agent_id: str) -> _AgentBreakerState:
        """Get or create internal state for an agent."""
        if agent_id not in self._agents:
            self._agents[agent_id] = _AgentBreakerState()
        return self._agents[agent_id]

    def forget(self, agent_id: str) -> None:
        """Drop all state for an agent (call on archive/kill).

        Args:
            agent_id: The agent whose state should be removed.
        """
        self._agents.pop(agent_id, None)

    def level_for(self, agent_id: str) -> BreakerLevel:
        """Current breaker level for an agent.

        Args:
            agent_id: The agent to query.

        Returns:
            The current BreakerLevel, or HEALTHY if unknown.
        """
        state = self._agents.get(agent_id)
        if state is None:
            return BreakerLevel.HEALTHY
        return state.level

    # ── Event-driven inputs ──────────────────────────────────────────────────

    def record_tool_use(
        self,
        agent_id: str,
        tool_name: str | None,
        tool_input: Any,
        now: float | None = None,
    ) -> None:
        """Record a tool call for loop detection.

        A new (name+input) key counts as forward progress (resets repeat and
        error counters). The same key in a row increments the loop counter.

        Args:
            agent_id: The agent that made the tool call.
            tool_name: Name of the tool, or None.
            tool_input: The tool's input payload.
            now: Current timestamp in ms (defaults to time.time() * 1000).
        """
        if now is None:
            now = time.time() * 1000
        state = self._get_state(agent_id)
        key = self._tool_key(tool_name, tool_input)
        if key == state.repeat_key:
            state.repeat_count += 1
        else:
            state.repeat_key = key
            state.repeat_count = 1
            state.error_count = 0
            state.last_distinct_tool_at = now

    def record_error(self, agent_id: str) -> None:
        """Record an api_error/retry event (no forward progress).

        Args:
            agent_id: The agent that encountered the error.
        """
        self._get_state(agent_id).error_count += 1

    def record_compact_start(self, agent_id: str, now: float | None = None) -> None:
        """Record that compaction started (PreCompact hook).

        Exempts velocity-based trips during compaction since compaction burns
        output tokens without touching coordination files.

        Args:
            agent_id: The agent undergoing compaction.
            now: Current timestamp in ms (defaults to time.time() * 1000).
        """
        if now is None:
            now = time.time() * 1000
        self._get_state(agent_id).compacting_until = now + COMPACT_GRACE_MS

    def record_compact_end(self, agent_id: str, now: float | None = None) -> None:
        """Record that compaction finished (PostCompact or SessionStart).

        Shortens the exemption to a trailing grace period. A no-op when no
        compaction is in flight.

        Args:
            agent_id: The agent that finished compaction.
            now: Current timestamp in ms (defaults to time.time() * 1000).
        """
        if now is None:
            now = time.time() * 1000
        state = self._get_state(agent_id)
        if state.compacting_until > now:
            state.compacting_until = now + POST_COMPACT_GRACE_MS

    # ── Periodic evaluation ──────────────────────────────────────────────────

    def tick(self, inputs: list[BreakerInput], now_ms: float) -> list[BreakerDecision]:
        """Evaluate every agent for this beat and return a decision per agent.

        Args:
            inputs: List of per-agent inputs for this beat.
            now_ms: Current timestamp in milliseconds.

        Returns:
            List of BreakerDecision, one per input agent.
        """
        cfg = self._get_config()
        decisions: list[BreakerDecision] = []

        if not cfg.enabled:
            # Breaker off: report healthy for everyone, take no action.
            for inp in inputs:
                state = self._get_state(inp.agent_id)
                changed = state.level != BreakerLevel.HEALTHY
                state.level = BreakerLevel.HEALTHY
                state.reason = ""
                decisions.append(BreakerDecision(
                    state=BreakerState(
                        agent_id=inp.agent_id,
                        level=BreakerLevel.HEALTHY,
                        reason="",
                        ts=now_ms,
                    ),
                    action=BreakerAction.NONE,
                    changed=changed,
                ))
            return decisions

        # Floor-wide cost cap: sum cumulative usd, blame the single biggest spender
        top_spender: str | None = None
        if cfg.cost_cap_usd is not None and cfg.cost_cap_usd > 0:
            total_usd = 0.0
            max_usd = -1.0
            for inp in inputs:
                usd = inp.sample.usd if inp.sample else 0.0
                total_usd += usd
                if usd > max_usd:
                    max_usd = usd
                    top_spender = inp.agent_id
            if total_usd <= cfg.cost_cap_usd:
                top_spender = None  # under cap, nobody blamed

        # Floor-wide token cap: sum total tokens, blame the single biggest spender
        top_token_spender: str | None = None
        if cfg.cost_cap_tokens is not None and cfg.cost_cap_tokens > 0:
            total_tokens = 0
            max_tokens = -1
            for inp in inputs:
                tok = _tokens_of(inp.sample)
                total_tokens += tok
                if tok > max_tokens:
                    max_tokens = tok
                    top_token_spender = inp.agent_id
            if total_tokens <= cfg.cost_cap_tokens:
                top_token_spender = None  # under cap

        for inp in inputs:
            state = self._get_state(inp.agent_id)
            trip = self._evaluate(
                inp, state, cfg, now_ms,
                is_top_spender=(inp.agent_id == top_spender),
                cost_cap_usd=cfg.cost_cap_usd,
                is_top_token_spender=(inp.agent_id == top_token_spender),
                cost_cap_tokens=cfg.cost_cap_tokens,
            )

            # Remember the cumulative baseline for next beat's velocity diff
            if inp.sample is not None:
                state.last_sample = inp.sample

            ceiling = BreakerLevel.STOPPED if cfg.hard_stop else BreakerLevel.CONSTRAINED
            target = state.level

            if trip[0]:
                # Escalate one level, capped at ceiling
                target = BreakerLevel(min(state.level + 1, ceiling))
            else:
                # De-escalate one level toward healthy
                target = BreakerLevel(max(state.level - 1, 0))

            changed = target != state.level
            escalated = target > state.level
            state.level = target

            if trip[0]:
                state.reason = trip[1]
            elif changed:
                state.reason = "recovering - signals cleared"

            decisions.append(BreakerDecision(
                state=BreakerState(
                    agent_id=inp.agent_id,
                    level=target,
                    reason=state.reason,
                    ts=now_ms,
                ),
                action=_action_for(target) if escalated else BreakerAction.NONE,
                changed=changed,
            ))

        return decisions

    # ── Private helpers ──────────────────────────────────────────────────────

    def _evaluate(
        self,
        inp: BreakerInput,
        state: _AgentBreakerState,
        cfg: BreakerConfig,
        now_ms: float,
        is_top_spender: bool,
        cost_cap_usd: float | None,
        is_top_token_spender: bool,
        cost_cap_tokens: int | None,
    ) -> tuple[bool, str]:
        """Evaluate trip conditions for one agent.

        Returns a tuple of (tripping, reason). Conditions are checked in order
        and the first match short-circuits.
        """
        # 1. Repeated identical tool calls
        if state.repeat_count >= cfg.repeated_tool_limit:
            tool_name = state.repeat_key.split(":")[0] if state.repeat_key else "?"
            return (
                True,
                f"looping: {state.repeat_count}x identical tool call ({tool_name})",
            )

        # 2. Error storm
        if state.error_count >= cfg.error_storm_limit:
            return (
                True,
                f"error storm: {state.error_count} consecutive api errors/retries",
            )

        # 3. Per-agent token cap
        if cfg.agent_token_caps is not None:
            per_agent_cap = cfg.agent_token_caps.get(inp.agent_id)
            if per_agent_cap is not None and per_agent_cap > 0:
                agent_tokens = _tokens_of(inp.sample)
                if agent_tokens > per_agent_cap:
                    return (
                        True,
                        f"token limit: {agent_tokens:,} over the agent cap of {per_agent_cap:,}",
                    )

        # 4. Floor-wide cost cap - this agent is top spender
        if is_top_spender and cost_cap_usd is not None:
            usd = inp.sample.usd if inp.sample else 0.0
            return (
                True,
                f"cost cap: floor total over ${cost_cap_usd} (top spender ${usd:.2f})",
            )

        # 5. Floor-wide token cap - this agent is top token spender
        if is_top_token_spender and cost_cap_tokens is not None:
            tok = _tokens_of(inp.sample)
            return (
                True,
                f"token cap: floor total over {cost_cap_tokens:,} tokens"
                f" (top spender {tok:,})",
            )

        # 6. Token velocity spike + 7. No-progress detection
        if inp.sample is not None and state.last_sample is not None:
            if now_ms >= state.compacting_until:
                d_out = inp.sample.output - state.last_sample.output
                d_min = (inp.sample.ts - state.last_sample.ts) / 60_000
                if d_out > 0 and d_min > 0:
                    velocity = d_out / d_min
                    if velocity > cfg.token_velocity_per_min:
                        return (
                            True,
                            f"token velocity {round(velocity)}/min"
                            f" > {cfg.token_velocity_per_min}/min",
                        )
                    # No-progress detection (within velocity check)
                    tool_active = (
                        now_ms - state.last_distinct_tool_at < PROGRESS_TOOL_WINDOW_MS
                    )
                    if not inp.progressing and not tool_active:
                        state.no_progress_beats += 1
                        if state.no_progress_beats >= NO_PROGRESS_BEATS:
                            return (
                                True,
                                "no-progress: generating tokens without coordinating"
                                " (stale log/files)",
                            )
                    else:
                        state.no_progress_beats = 0

        return (False, "")

    def _tool_key(self, tool_name: str | None, tool_input: Any) -> str:
        """Build a deduplication key from tool name and truncated input.

        String values longer than 250 chars are truncated before serialization,
        and the final key is sliced to 200 chars.
        """
        name = tool_name if tool_name is not None else "?"
        inp_str = ""
        try:
            inp_str = json.dumps(
                tool_input,
                default=lambda v: str(v),
                sort_keys=True,
            )
            # Re-serialize with truncation for string values
            inp_str = json.dumps(
                tool_input,
                default=lambda v: str(v)[:250] if len(str(v)) > 250 else str(v),
            )
            # Apply truncation replacer properly via custom encoder approach
            inp_str = self._truncated_json(tool_input)
        except (TypeError, ValueError):
            inp_str = str(tool_input)
        return f"{name}:{inp_str[:200]}"

    def _truncated_json(self, obj: Any) -> str:
        """Serialize object to JSON, truncating string values > 250 chars."""
        def replacer(o: Any) -> Any:
            if isinstance(o, str) and len(o) > 250:
                return o[:250]
            if isinstance(o, dict):
                return {k: replacer(v) for k, v in o.items()}
            if isinstance(o, (list, tuple)):
                return [replacer(item) for item in o]
            return o

        try:
            truncated = replacer(obj)
            return json.dumps(truncated, default=str)
        except (TypeError, ValueError):
            return str(obj)
