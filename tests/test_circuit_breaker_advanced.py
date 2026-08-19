"""Comprehensive tests for the AdvancedCircuitBreaker module."""

import pytest

from nexus.governance.breaker_types import (
    AgentUsageSample,
    BreakerAction,
    BreakerConfig,
    BreakerDecision,
    BreakerInput,
    BreakerLevel,
    BreakerState,
)
from nexus.governance.circuit_breaker_advanced import (
    COMPACT_GRACE_MS,
    NO_PROGRESS_BEATS,
    POST_COMPACT_GRACE_MS,
    PROGRESS_TOOL_WINDOW_MS,
    AdvancedCircuitBreaker,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_sample(
    input_: int = 100,
    output: int = 100,
    cache_read: int = 0,
    cache_creation: int = 0,
    usd: float = 0.01,
    ts: float = 1_000_000.0,
) -> AgentUsageSample:
    """Create a test usage sample with convenient defaults."""
    return AgentUsageSample(
        input=input_,
        output=output,
        cache_read=cache_read,
        cache_creation=cache_creation,
        usd=usd,
        ts=ts,
    )


def _default_config(**overrides) -> BreakerConfig:
    """Create a BreakerConfig with optional overrides."""
    return BreakerConfig(**overrides)


def _make_breaker(config: BreakerConfig | None = None) -> AdvancedCircuitBreaker:
    """Create an AdvancedCircuitBreaker with a fixed config."""
    cfg = config or _default_config()
    return AdvancedCircuitBreaker(config_getter=lambda: cfg)


# ── Test: Repeated Tool Calls Trip ───────────────────────────────────────────


class TestRepeatedToolCallsTrip:
    """Tests for the repeated tool call loop detection."""

    def test_trips_at_limit(self):
        """Recording the same tool N times (>= limit) triggers escalation."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=3))
        now = 1_000_000.0

        # Record same tool 3 times
        for _ in range(3):
            breaker.record_tool_use("agent-1", "read_file", {"path": "/foo"}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert len(decisions) == 1
        assert decisions[0].state.level == BreakerLevel.STEERING
        assert decisions[0].action == BreakerAction.STEER
        assert decisions[0].changed is True
        assert "looping" in decisions[0].state.reason

    def test_does_not_trip_below_limit(self):
        """Recording fewer than the limit does not trip."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=5))
        now = 1_000_000.0

        for _ in range(4):
            breaker.record_tool_use("agent-1", "read_file", {"path": "/foo"}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY

    def test_distinct_tool_resets_count(self):
        """A distinct tool call resets the repeat counter."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=3))
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read_file", {"path": "/foo"}, now)
        breaker.record_tool_use("agent-1", "read_file", {"path": "/foo"}, now)
        # Different tool call resets
        breaker.record_tool_use("agent-1", "write_file", {"path": "/bar"}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: Error Storm Trip ───────────────────────────────────────────────────


class TestErrorStormTrip:
    """Tests for the error storm detection."""

    def test_trips_at_limit(self):
        """Recording N consecutive errors triggers escalation."""
        breaker = _make_breaker(_default_config(error_storm_limit=3))
        now = 1_000_000.0

        for _ in range(3):
            breaker.record_error("agent-1")

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.STEERING
        assert decisions[0].action == BreakerAction.STEER
        assert "error storm" in decisions[0].state.reason

    def test_does_not_trip_below_limit(self):
        """Fewer errors than the limit does not trip."""
        breaker = _make_breaker(_default_config(error_storm_limit=5))
        now = 1_000_000.0

        for _ in range(4):
            breaker.record_error("agent-1")

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY

    def test_distinct_tool_clears_errors(self):
        """A distinct tool call clears the error counter."""
        breaker = _make_breaker(_default_config(error_storm_limit=3))
        now = 1_000_000.0

        breaker.record_error("agent-1")
        breaker.record_error("agent-1")
        # Distinct tool call clears errors
        breaker.record_tool_use("agent-1", "write_file", {"path": "/bar"}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: Per-Agent Token Cap ────────────────────────────────────────────────


class TestPerAgentTokenCap:
    """Tests for per-agent token cap enforcement."""

    def test_trips_when_over_cap(self):
        """Agent with tokens exceeding its cap triggers escalation."""
        breaker = _make_breaker(
            _default_config(agent_token_caps={"agent-1": 1000})
        )
        now = 1_000_000.0

        # Total tokens = 500 + 600 + 0 + 0 = 1100 > 1000
        sample = _make_sample(input_=500, output=600, ts=now)
        inp = BreakerInput(agent_id="agent-1", sample=sample, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.STEERING
        assert "token limit" in decisions[0].state.reason

    def test_does_not_trip_under_cap(self):
        """Agent with tokens under its cap does not trip."""
        breaker = _make_breaker(
            _default_config(agent_token_caps={"agent-1": 2000})
        )
        now = 1_000_000.0

        sample = _make_sample(input_=500, output=400, ts=now)
        inp = BreakerInput(agent_id="agent-1", sample=sample, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY

    def test_only_affects_configured_agent(self):
        """Agents without a cap are not affected."""
        breaker = _make_breaker(
            _default_config(agent_token_caps={"agent-1": 1000})
        )
        now = 1_000_000.0

        sample = _make_sample(input_=5000, output=5000, ts=now)
        inp = BreakerInput(agent_id="agent-2", sample=sample, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: Cost Cap Blames Top Spender ────────────────────────────────────────


class TestCostCapBlamesToppSpender:
    """Tests for floor-wide cost cap enforcement."""

    def test_only_top_spender_trips(self):
        """Only the top spender is blamed when floor total exceeds cost cap."""
        breaker = _make_breaker(_default_config(cost_cap_usd=1.00))
        now = 1_000_000.0

        sample1 = _make_sample(usd=0.80, ts=now)
        sample2 = _make_sample(usd=0.30, ts=now)
        inputs = [
            BreakerInput(agent_id="agent-1", sample=sample1, progressing=True),
            BreakerInput(agent_id="agent-2", sample=sample2, progressing=True),
        ]
        decisions = breaker.tick(inputs, now)

        # Total = 1.10 > 1.00, agent-1 is top spender
        agent1_decision = next(d for d in decisions if d.state.agent_id == "agent-1")
        agent2_decision = next(d for d in decisions if d.state.agent_id == "agent-2")

        assert agent1_decision.state.level == BreakerLevel.STEERING
        assert "cost cap" in agent1_decision.state.reason
        assert agent2_decision.state.level == BreakerLevel.HEALTHY

    def test_nobody_trips_under_cap(self):
        """Nobody trips when total is under the cap."""
        breaker = _make_breaker(_default_config(cost_cap_usd=5.00))
        now = 1_000_000.0

        sample1 = _make_sample(usd=1.00, ts=now)
        sample2 = _make_sample(usd=1.00, ts=now)
        inputs = [
            BreakerInput(agent_id="agent-1", sample=sample1, progressing=True),
            BreakerInput(agent_id="agent-2", sample=sample2, progressing=True),
        ]
        decisions = breaker.tick(inputs, now)

        assert all(d.state.level == BreakerLevel.HEALTHY for d in decisions)


# ── Test: Token Velocity Spike ───────────────────────────────────────────────


class TestTokenVelocitySpike:
    """Tests for token velocity spike detection."""

    def test_high_velocity_trips(self):
        """Two consecutive samples with high output delta triggers a trip."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1000)
        )

        # First tick establishes baseline
        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=True)
        breaker.tick([inp1], t1)

        # Second tick 30 seconds later with huge output delta
        t2 = t1 + 30_000  # 30 seconds = 0.5 min
        # Delta output = 100000, over 0.5 min = 200000/min >> 1000/min
        sample2 = _make_sample(output=101_000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=True)
        decisions = breaker.tick([inp2], t2)

        assert decisions[0].state.level == BreakerLevel.STEERING
        assert "velocity" in decisions[0].state.reason

    def test_normal_velocity_does_not_trip(self):
        """Normal output rate does not trigger."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=60_000)
        )

        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=True)
        breaker.tick([inp1], t1)

        # 60 seconds later, 1000 more tokens = 1000/min << 60000/min
        t2 = t1 + 60_000
        sample2 = _make_sample(output=2000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=True)
        decisions = breaker.tick([inp2], t2)

        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: No-Progress Debounce ───────────────────────────────────────────────


class TestNoProgressDebounce:
    """Tests for no-progress detection with debouncing."""

    def test_needs_two_consecutive_beats(self):
        """No-progress detection requires 2 consecutive beats to fire."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1_000_000)  # high so velocity doesnt trip
        )

        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=False)
        breaker.tick([inp1], t1)

        # Beat 2: still no progress, but only 1 beat so far - should not trip yet
        t2 = t1 + 60_000
        sample2 = _make_sample(output=2000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=False)
        decisions = breaker.tick([inp2], t2)
        assert decisions[0].state.level == BreakerLevel.HEALTHY

        # Beat 3: still no progress, now 2 consecutive beats - should trip
        t3 = t2 + 60_000
        sample3 = _make_sample(output=3000, ts=t3)
        inp3 = BreakerInput(agent_id="agent-1", sample=sample3, progressing=False)
        decisions = breaker.tick([inp3], t3)
        assert decisions[0].state.level == BreakerLevel.STEERING
        assert "no-progress" in decisions[0].state.reason

    def test_progress_resets_counter(self):
        """A beat with progress resets the no-progress counter."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1_000_000)
        )

        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=False)
        breaker.tick([inp1], t1)

        # Beat 2: no progress - 1 beat
        t2 = t1 + 60_000
        sample2 = _make_sample(output=2000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=False)
        breaker.tick([inp2], t2)

        # Beat 3: WITH progress - resets counter
        t3 = t2 + 60_000
        sample3 = _make_sample(output=3000, ts=t3)
        inp3 = BreakerInput(agent_id="agent-1", sample=sample3, progressing=True)
        breaker.tick([inp3], t3)

        # Beat 4: no progress again - only 1 beat since reset, should not trip
        t4 = t3 + 60_000
        sample4 = _make_sample(output=4000, ts=t4)
        inp4 = BreakerInput(agent_id="agent-1", sample=sample4, progressing=False)
        decisions = breaker.tick([inp4], t4)
        assert decisions[0].state.level == BreakerLevel.HEALTHY

    def test_tool_activity_counts_as_progress(self):
        """A recent distinct tool call counts as progress for no-progress arm."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1_000_000)
        )

        t1 = 1_000_000.0
        # Record a distinct tool call now
        breaker.record_tool_use("agent-1", "read_file", {"path": "/a"}, t1)

        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=False)
        breaker.tick([inp1], t1)

        # Beat 2: within tool window, even without progressing flag
        t2 = t1 + 60_000  # 1 min later, still within PROGRESS_TOOL_WINDOW_MS
        sample2 = _make_sample(output=2000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=False)
        breaker.tick([inp2], t2)

        # Beat 3: still within tool window
        t3 = t2 + 60_000
        sample3 = _make_sample(output=3000, ts=t3)
        inp3 = BreakerInput(agent_id="agent-1", sample=sample3, progressing=False)
        decisions = breaker.tick([inp3], t3)

        # Should not trip because tool activity counts as progress
        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: Escalation One Level Per Tick ──────────────────────────────────────


class TestEscalationOneLevelPerTick:
    """Tests that escalation only moves one level per tick."""

    def test_healthy_to_steering(self):
        """First trip goes from HEALTHY to STEERING."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=2))
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.STEERING

    def test_steering_to_constrained(self):
        """Second consecutive trip goes from STEERING to CONSTRAINED."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=2))
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        breaker.tick([inp], now)  # -> STEERING

        # Still tripping
        decisions = breaker.tick([inp], now)  # -> CONSTRAINED
        assert decisions[0].state.level == BreakerLevel.CONSTRAINED

    def test_never_jumps_two_levels(self):
        """Even with severe trip, escalation is limited to one level per tick."""
        breaker = _make_breaker(
            _default_config(repeated_tool_limit=2, hard_stop=True)
        )
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        # Even with hard_stop, first escalation is only to STEERING (not STOPPED)
        assert decisions[0].state.level == BreakerLevel.STEERING


# ── Test: De-escalation One Level Per Tick ───────────────────────────────────


class TestDeEscalationOneLevelPerTick:
    """Tests that de-escalation only moves one level per healthy tick."""

    def test_constrained_to_steering_to_healthy(self):
        """Recovery goes one level per healthy tick."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=2))
        now = 1_000_000.0

        # Force to CONSTRAINED (2 escalations)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        breaker.tick([inp], now)  # -> STEERING
        breaker.tick([inp], now)  # -> CONSTRAINED

        assert breaker.level_for("agent-1") == BreakerLevel.CONSTRAINED

        # Now clear the trip condition
        breaker.record_tool_use("agent-1", "different_tool", {"x": 1}, now)

        # First healthy tick: CONSTRAINED -> STEERING
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.STEERING

        # Second healthy tick: STEERING -> HEALTHY
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: Compaction Exemption ───────────────────────────────────────────────


class TestCompactionExemption:
    """Tests for compaction exemption of velocity trips."""

    def test_velocity_suppressed_during_compaction(self):
        """After record_compact_start, velocity trips are suppressed."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1000)
        )

        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=True)
        breaker.tick([inp1], t1)

        # Start compaction
        breaker.record_compact_start("agent-1", t1 + 1000)

        # High velocity tick during compaction grace period
        t2 = t1 + 30_000
        sample2 = _make_sample(output=101_000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=True)
        decisions = breaker.tick([inp2], t2)

        # Should NOT trip because compaction is in flight
        assert decisions[0].state.level == BreakerLevel.HEALTHY

    def test_velocity_trips_after_grace_expires(self):
        """After the compaction grace expires, velocity trips resume."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1000)
        )

        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=True)
        breaker.tick([inp1], t1)

        # Start compaction
        breaker.record_compact_start("agent-1", t1)

        # Tick AFTER grace expires
        t2 = t1 + COMPACT_GRACE_MS + 60_000  # well past grace
        sample2 = _make_sample(output=500_000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=True)
        decisions = breaker.tick([inp2], t2)

        # Should trip because grace has expired
        assert decisions[0].state.level == BreakerLevel.STEERING
        assert "velocity" in decisions[0].state.reason


# ── Test: Compact End Shortens Grace ─────────────────────────────────────────


class TestCompactEndShortensGrace:
    """Tests for record_compact_end shortening the grace period."""

    def test_shortens_to_post_compact_grace(self):
        """record_compact_end shortens exemption to POST_COMPACT_GRACE_MS."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1000)
        )

        t1 = 1_000_000.0
        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=True)
        breaker.tick([inp1], t1)

        # Start compaction (grace = 5 minutes)
        breaker.record_compact_start("agent-1", t1)
        # End compaction immediately (grace shortened to 90s)
        breaker.record_compact_end("agent-1", t1 + 1000)

        # Tick AFTER post-compact grace but BEFORE original grace would expire
        t2 = t1 + POST_COMPACT_GRACE_MS + 60_000  # ~2.5 min, past 90s but before 5min
        sample2 = _make_sample(output=500_000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=True)
        decisions = breaker.tick([inp2], t2)

        # Should trip because shortened grace has expired
        assert decisions[0].state.level == BreakerLevel.STEERING

    def test_noop_without_active_compaction(self):
        """record_compact_end does nothing if no compaction is in flight."""
        breaker = _make_breaker(
            _default_config(token_velocity_per_min=1000)
        )

        t1 = 1_000_000.0
        # No compact_start, just compact_end
        breaker.record_compact_end("agent-1", t1)

        sample1 = _make_sample(output=1000, ts=t1)
        inp1 = BreakerInput(agent_id="agent-1", sample=sample1, progressing=True)
        breaker.tick([inp1], t1)

        # High velocity should still trip (no exemption was granted)
        t2 = t1 + 30_000
        sample2 = _make_sample(output=101_000, ts=t2)
        inp2 = BreakerInput(agent_id="agent-1", sample=sample2, progressing=True)
        decisions = breaker.tick([inp2], t2)

        assert decisions[0].state.level == BreakerLevel.STEERING


# ── Test: Forget Removes State ───────────────────────────────────────────────


class TestForgetRemovesState:
    """Tests for the forget() method."""

    def test_forget_resets_to_healthy(self):
        """After forget(), level_for returns HEALTHY."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=2))
        now = 1_000_000.0

        # Escalate to STEERING
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        breaker.tick([inp], now)

        assert breaker.level_for("agent-1") == BreakerLevel.STEERING

        # Forget the agent
        breaker.forget("agent-1")
        assert breaker.level_for("agent-1") == BreakerLevel.HEALTHY

    def test_forget_clears_trip_state(self):
        """After forget(), repeat counters are gone."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=3))
        now = 1_000_000.0

        # Record 2 repeats
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        breaker.forget("agent-1")

        # Record 1 more of the same tool - total is 1, not 3
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.HEALTHY


# ── Test: Disabled Breaker All Healthy ───────────────────────────────────────


class TestDisabledBreakerAllHealthy:
    """Tests for disabled breaker behavior."""

    def test_all_agents_report_healthy(self):
        """With enabled=False, all agents are reported healthy."""
        breaker = _make_breaker(_default_config(enabled=False, repeated_tool_limit=1))
        now = 1_000_000.0

        # Even with a trip condition met
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY
        assert decisions[0].action == BreakerAction.NONE

    def test_resets_escalated_agents(self):
        """Disabling the breaker resets previously escalated agents."""
        cfg = _default_config(repeated_tool_limit=2)
        breaker = AdvancedCircuitBreaker(config_getter=lambda: cfg)
        now = 1_000_000.0

        # Escalate to STEERING
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        breaker.tick([inp], now)
        assert breaker.level_for("agent-1") == BreakerLevel.STEERING

        # Now tick with disabled config
        disabled_cfg = _default_config(enabled=False)
        breaker2 = AdvancedCircuitBreaker(config_getter=lambda: disabled_cfg)
        # Simulate: use the same breaker but change config
        breaker._config_getter = lambda: disabled_cfg
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.HEALTHY
        assert decisions[0].changed is True


# ── Test: Hard Stop Allows STOPPED ───────────────────────────────────────────


class TestHardStopAllowsStopped:
    """Tests for hard_stop=True behavior."""

    def test_can_escalate_to_stopped(self):
        """With hard_stop=True, agents can reach STOPPED level."""
        breaker = _make_breaker(
            _default_config(repeated_tool_limit=2, hard_stop=True)
        )
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)

        # Tick 1: HEALTHY -> STEERING
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.STEERING

        # Tick 2: STEERING -> CONSTRAINED
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.CONSTRAINED

        # Tick 3: CONSTRAINED -> STOPPED
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.STOPPED
        assert decisions[0].action == BreakerAction.STOP


# ── Test: No Hard Stop Caps at CONSTRAINED ───────────────────────────────────


class TestNoHardStopCapsAtConstrained:
    """Tests for hard_stop=False ceiling behavior."""

    def test_caps_at_constrained(self):
        """Without hard_stop, max level is CONSTRAINED even with persistent trips."""
        breaker = _make_breaker(
            _default_config(repeated_tool_limit=2, hard_stop=False)
        )
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)

        # Tick 1: HEALTHY -> STEERING
        breaker.tick([inp], now)
        # Tick 2: STEERING -> CONSTRAINED
        breaker.tick([inp], now)
        # Tick 3: should stay at CONSTRAINED
        decisions = breaker.tick([inp], now)

        assert decisions[0].state.level == BreakerLevel.CONSTRAINED
        # No escalation, so no action
        assert decisions[0].action == BreakerAction.NONE


# ── Test: Action Only On Escalation ──────────────────────────────────────────


class TestActionOnlyOnEscalation:
    """Tests that action fires only on escalation."""

    def test_no_action_when_level_stays_same(self):
        """Action is NONE when the level stays the same (sustained trip at ceiling)."""
        breaker = _make_breaker(
            _default_config(repeated_tool_limit=2, hard_stop=False)
        )
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        breaker.tick([inp], now)  # -> STEERING (action=steer)
        breaker.tick([inp], now)  # -> CONSTRAINED (action=constrain)
        decisions = breaker.tick([inp], now)  # stays CONSTRAINED

        assert decisions[0].state.level == BreakerLevel.CONSTRAINED
        assert decisions[0].action == BreakerAction.NONE
        assert decisions[0].changed is False

    def test_no_action_on_deescalation(self):
        """Action is NONE on de-escalation (recovery)."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=2))
        now = 1_000_000.0

        # Escalate to STEERING
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        breaker.tick([inp], now)

        # Clear trip
        breaker.record_tool_use("agent-1", "other_tool", {"b": 2}, now)

        # De-escalation tick
        decisions = breaker.tick([inp], now)
        assert decisions[0].state.level == BreakerLevel.HEALTHY
        assert decisions[0].action == BreakerAction.NONE
        assert decisions[0].changed is True

    def test_action_fires_on_escalation(self):
        """Action fires when level escalates."""
        breaker = _make_breaker(_default_config(repeated_tool_limit=2))
        now = 1_000_000.0

        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)
        breaker.record_tool_use("agent-1", "read", {"a": 1}, now)

        inp = BreakerInput(agent_id="agent-1", sample=None, progressing=True)
        decisions = breaker.tick([inp], now)

        assert decisions[0].action == BreakerAction.STEER
        assert decisions[0].changed is True


# ── Test: Floor-Wide Token Cap ───────────────────────────────────────────────


class TestFloorWideTokenCap:
    """Tests for floor-wide token cap enforcement."""

    def test_only_top_token_spender_trips(self):
        """Only the top token spender is blamed when total exceeds cap."""
        breaker = _make_breaker(_default_config(cost_cap_tokens=5000))
        now = 1_000_000.0

        sample1 = _make_sample(input_=2000, output=2000, ts=now)  # 4000 tokens
        sample2 = _make_sample(input_=500, output=600, ts=now)  # 1100 tokens
        inputs = [
            BreakerInput(agent_id="agent-1", sample=sample1, progressing=True),
            BreakerInput(agent_id="agent-2", sample=sample2, progressing=True),
        ]
        # Total = 5100 > 5000
        decisions = breaker.tick(inputs, now)

        agent1_decision = next(d for d in decisions if d.state.agent_id == "agent-1")
        agent2_decision = next(d for d in decisions if d.state.agent_id == "agent-2")

        assert agent1_decision.state.level == BreakerLevel.STEERING
        assert "token cap" in agent1_decision.state.reason
        assert agent2_decision.state.level == BreakerLevel.HEALTHY


# ── Test: Types and Exports ──────────────────────────────────────────────────


class TestTypesAndExports:
    """Test that all types are properly accessible via governance package."""

    def test_imports_from_governance(self):
        """All key types are importable from nexus.governance."""
        from nexus.governance import (
            AgentUsageSample,
            AdvancedCircuitBreaker,
            BreakerAction,
            BreakerConfig,
            BreakerDecision,
            BreakerInput,
            BreakerLevel,
            BreakerState,
        )

        assert BreakerLevel.HEALTHY == 0
        assert BreakerLevel.STEERING == 1
        assert BreakerLevel.CONSTRAINED == 2
        assert BreakerLevel.STOPPED == 3

        assert BreakerAction.NONE == "none"
        assert BreakerAction.STEER == "steer"
        assert BreakerAction.CONSTRAIN == "constrain"
        assert BreakerAction.STOP == "stop"

    def test_agent_usage_sample_creation(self):
        """AgentUsageSample can be created with all fields."""
        sample = AgentUsageSample(
            input=100, output=200, cache_read=50, cache_creation=10, usd=0.05, ts=123.0
        )
        assert sample.input == 100
        assert sample.output == 200
        assert sample.cache_read == 50
        assert sample.cache_creation == 10
        assert sample.usd == 0.05
        assert sample.ts == 123.0

    def test_breaker_config_defaults(self):
        """BreakerConfig has sensible defaults."""
        config = BreakerConfig()
        assert config.enabled is True
        assert config.hard_stop is False
        assert config.repeated_tool_limit == 8
        assert config.error_storm_limit == 5
        assert config.token_velocity_per_min == 60_000
        assert config.cost_cap_usd is None
        assert config.cost_cap_tokens is None
        assert config.agent_token_caps is None
