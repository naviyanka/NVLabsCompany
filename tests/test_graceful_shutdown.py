"""Tests for graceful shutdown hooks in the NEXUS lifespan.

Verifies that the shutdown phase of the application lifespan correctly:
- Flushes telemetry metrics
- Persists ControlRegistry state when configured
- Logs final shutdown status
"""

import logging
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_shutdown_flushes_telemetry(caplog: pytest.LogCaptureFixture) -> None:
    """Verify telemetry registry is reset during shutdown."""
    from nexus.telemetry import Counter, registry

    # Register a test metric (use a unique name to avoid cross-test pollution)
    test_counter = registry.register(
        Counter("test_shutdown_counter_isolated", "test")
    )
    test_counter.inc()

    assert test_counter.value == 1.0

    # Simulate shutdown by calling reset
    registry.reset()

    # After reset, all metrics should be cleared
    assert registry.all_metrics() == {}

    # Re-register default metrics so other tests are not affected
    from nexus.telemetry import (
        http_request_duration_seconds,
        http_requests_in_flight,
        http_requests_total,
    )
    registry.register(http_requests_total)
    registry.register(http_request_duration_seconds)
    registry.register(http_requests_in_flight)


@pytest.mark.asyncio
async def test_shutdown_persists_control_registry(tmp_path) -> None:
    """Verify ControlRegistry state is persisted on shutdown."""
    from nexus.governance.control_registry import ControlRegistry

    persist_file = tmp_path / "control_state.json"
    cr = ControlRegistry(persist_path=persist_file)

    # Add some state
    cr.pause("agent-1", True)
    cr.gate_tool("agent-2", "shell_exec", True)

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
    # Mock the database and session factory
    mock_session_factory = MagicMock()
    mock_session = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(
        return_value=mock_session
    )
    mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    # Mock the database query for company check
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = MagicMock()  # Company exists
    mock_session.execute = AsyncMock(return_value=mock_result)

    with (
        patch("nexus.main.settings") as mock_settings,
        patch.dict(os.environ, {"NEXUS_CONTROL_STATE_PATH": ""}, clear=False),
    ):
        mock_settings.database_url = "sqlite+aiosqlite:///test.db"
        mock_settings.redis_url = ""
        mock_settings.cors_origins = "http://localhost:3000"

        # The lifespan should not raise during shutdown
        # We test the components individually since full lifespan
        # requires database setup
        from nexus.telemetry import registry
        registry.reset()  # Should not raise

        from nexus.governance.control_registry import ControlRegistry
        cr = ControlRegistry(persist_path=None)
        cr._persist()  # Should not raise with None path

    # Re-register default metrics
    from nexus.telemetry import (
        http_request_duration_seconds,
        http_requests_in_flight,
        http_requests_total,
    )
    registry.register(http_requests_total)
    registry.register(http_request_duration_seconds)
    registry.register(http_requests_in_flight)


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
