"""Circuit breaker types - escalation levels, actions, signals, and configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, Enum


class BreakerLevel(IntEnum):
    """Four-level escalation ladder for circuit breaker state."""

    HEALTHY = 0
    STEERING = 1
    CONSTRAINED = 2
    STOPPED = 3


class BreakerAction(str, Enum):
    """Action the beat should take for an agent this tick."""

    NONE = "none"
    STEER = "steer"
    CONSTRAIN = "constrain"
    STOP = "stop"


@dataclass
class AgentUsageSample:
    """Cumulative usage snapshot for one agent at a point in time."""

    input: int
    output: int
    cache_read: int
    cache_creation: int
    usd: float
    ts: float


@dataclass
class BreakerState:
    """Emitted per agent per beat so dashboards stay live."""

    agent_id: str
    level: BreakerLevel
    reason: str
    ts: float


@dataclass
class BreakerDecision:
    """What the beat should do this tick for one agent."""

    state: BreakerState
    action: BreakerAction
    changed: bool


@dataclass
class BreakerInput:
    """Per-agent input for one beat."""

    agent_id: str
    sample: AgentUsageSample | None
    progressing: bool


@dataclass
class BreakerConfig:
    """Configuration for the advanced circuit breaker."""

    enabled: bool = True
    hard_stop: bool = False
    repeated_tool_limit: int = 8
    error_storm_limit: int = 5
    token_velocity_per_min: int = 60_000
    cost_cap_usd: float | None = None
    cost_cap_tokens: int | None = None
    agent_token_caps: dict[str, int] | None = None
