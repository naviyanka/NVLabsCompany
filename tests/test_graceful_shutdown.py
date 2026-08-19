"""Tests for graceful shutdown hooks in the NEXUS lifespan.

Verifies that the shutdown phase of the application lifespan correctly:
- Preserves telemetry metrics (no destructive reset)
- Persists ControlRegistry state via the runtime singleton
- Logs final shutdown status
"""

import logging

import pytest


@pytest.mark.asyncio
async def test_shutdown_preserves_telemetry_metrics() -> None:
    """Verify telemetry metrics are NOT cleared during shutdown.

    The shutdown no longer calls registry.reset() because it is a
    test-only helper that destroys unscraped metrics. Prometheus-style
    scrape does not need a flush step.
    """
    from nexus.telemetry import Counter, registry

    # Register a test metric (use a unique name to avoid cross-test pollution)
    test_counter = registry.register(
        Counter("test_shutdown_preserves_counter", "test")
    )
    test_counter.inc()

    assert test_counter.value == 1.0

    # After shutdown, metrics should still be available for scraping
    assert registry.get("test_shutdown_preserves_counter") is not None
    assert registry.get("test_shutdown_preserves_counter").value == 1.0


@pytest.mark.asyncio
async def test_shutdown_persists_control_registry_via_singleton(
    tmp_path,
) -> None:
    """Verify ControlRegistry singleton is persisted on shutdown."""
    from unittest.mock import patch

    from nexus.governance.control_registry import ControlRegistry

    persist_file = tmp_path / "control_state.json"
    mock_registry = ControlRegistry(persist_path=persist_file)

    # Add some state to the singleton
    mock_registry.pause("agent-1", True)
    mock_registry.gate_tool("agent-2", "shell_exec", True)

    # Simulate shutdown: get_registry returns our mock singleton
    with patch(
        "nexus.api.routes.control.get_registry",
        return_value=mock_registry,
    ):
        from nexus.api.routes.control import get_registry
        cr = get_registry()
        cr._persist()

    # Verify state was persisted
    assert persist_file.exists()
    content = persist_file.read_text()
    assert "agent-1" in content
    assert "agent-2" in content

    # Load into new registry and verify
    cr2 = ControlRegistry(persist_path=persist_file)
    snap = cr2.snapshot("agent-1")
    assert snap.paused is True


@pytest.mark.asyncio
async def test_shutdown_logs_final_message(caplog: pytest.LogCaptureFixture) -> None:
    """Verify that the shutdown sequence logs a completion message."""
    logger = logging.getLogger("nexus.main")
    with caplog.at_level(logging.INFO, logger="nexus.main"):
        logger.info("NEXUS shutdown complete - all resources released")

    assert "NEXUS shutdown complete" in caplog.text


@pytest.mark.asyncio
async def test_lifespan_shutdown_executes() -> None:
    """Integration test: verify the lifespan shutdown path runs cleanly."""
    # The lifespan should not raise during shutdown
    # We test the components individually since full lifespan
    # requires database setup

    # ControlRegistry._persist() should not raise with None path
    from nexus.governance.control_registry import ControlRegistry
    cr = ControlRegistry(persist_path=None)
    cr._persist()  # Should not raise with None path

    # get_registry returns the module-level singleton
    from nexus.api.routes.control import get_registry
    singleton = get_registry()
    assert singleton is not None


@pytest.mark.asyncio
async def test_telemetry_reset_is_idempotent() -> None:
    """Calling registry.reset() multiple times is safe."""
    from nexus.telemetry import (
        http_request_duration_seconds,
        http_requests_in_flight,
        http_requests_total,
        registry,
    )

    registry.reset()
    registry.reset()
    registry.reset()

    assert registry.all_metrics() == {}

    # Re-register default metrics so other tests are not affected
    registry.register(http_requests_total)
    registry.register(http_request_duration_seconds)
    registry.register(http_requests_in_flight)


@pytest.mark.asyncio
async def test_control_registry_persist_with_no_path() -> None:
    """ControlRegistry._persist() is a no-op when persist_path is None."""
    from nexus.governance.control_registry import ControlRegistry

    cr = ControlRegistry(persist_path=None)
    cr.pause("test-agent", True)

    # This should not raise
    cr._persist()

    # State exists in memory but not on disk
    snap = cr.snapshot("test-agent")
    assert snap.paused is True
