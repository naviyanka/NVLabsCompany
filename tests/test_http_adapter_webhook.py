"""Tests for HTTP Adapter webhook callback and enhanced polling.

Tests cover:
- Successful poll flow (202 -> poll -> completed)
- Poll timeout (max_polls exhausted)
- Poll with connection errors (distinct error handling)
- Callback registration
- Callback handler invocation
- Configurable poll parameters (poll_interval, max_polls, timeout)
- Capabilities include webhook_callback
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from nexus.adapters.http_adapter import CallbackRegistration, HTTPAdapter


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture
def adapter():
    """Create an HTTPAdapter instance."""
    return HTTPAdapter()


@pytest.fixture
def agent_id():
    """Fixed agent UUID for tests."""
    return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")


@pytest.fixture
def task_id():
    """Fixed task UUID for tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def config():
    """Default HTTP adapter config."""
    return {
        "base_url": "https://test-agent.example.com",
        "bearer_token": "test-token-123",
        "poll_interval": 0.1,
        "timeout": 5.0,
    }


@pytest.fixture
def session(adapter, agent_id, config):
    """Create a ready session for testing."""
    return _run(adapter.create_session(agent_id, config))


class TestPollForResultSuccessful:
    """Test successful poll flow: 202 -> poll -> completed."""

    def test_poll_returns_completed_result(self, adapter, session):
        """Polling returns data when status is 'completed'."""
        import httpx

        poll_responses = [
            httpx.Response(
                200,
                json={"status": "pending", "progress": 50},
            ),
            httpx.Response(
                200,
                json={
                    "status": "completed",
                    "output": "task done",
                    "success": True,
                },
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=poll_responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                )
            )

        assert result["status"] == "completed"
        assert result["output"] == "task done"
        assert result["success"] is True

    def test_poll_handles_done_status(self, adapter, session):
        """Polling recognizes 'done' as a terminal status."""
        import httpx

        poll_responses = [
            httpx.Response(
                200,
                json={"status": "done", "output": "finished"},
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=poll_responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                )
            )

        assert result["status"] == "done"

    def test_poll_handles_error_status(self, adapter, session):
        """Polling recognizes 'error' as a terminal status."""
        import httpx

        poll_responses = [
            httpx.Response(
                200,
                json={"status": "error", "error": "something broke"},
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=poll_responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                )
            )

        assert result["status"] == "error"
        assert result["error"] == "something broke"


class TestPollForResultTimeout:
    """Test poll timeout when max_polls is exhausted."""

    def test_poll_times_out_after_max_polls(self, adapter, session):
        """Polling returns timeout error when max_polls is reached."""
        import httpx

        # Always return pending status
        pending_response = httpx.Response(
            200, json={"status": "pending"}
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=pending_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                    max_polls=3,
                )
            )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        # Should have been called exactly 3 times
        assert mock_client.get.call_count == 3

    def test_poll_timeout_uses_session_defaults(self, adapter, session):
        """Polling uses session metadata for interval/timeout defaults."""
        import httpx

        pending_response = httpx.Response(
            200, json={"status": "pending"}
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=pending_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # Session has poll_interval=0.1 and timeout=5.0
        # So max_polls = 5.0 / 0.1 = 50
        # Override to a smaller value for test speed
        session.metadata["timeout"] = 0.3
        session.metadata["poll_interval"] = 0.01

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                )
            )

        assert result["success"] is False
        assert "timed out" in result["error"].lower()
        # max_polls = 0.3 / 0.01 = 30
        assert mock_client.get.call_count == 30


class TestPollForResultConnectionErrors:
    """Test poll behavior with connection errors."""

    def test_poll_fails_after_repeated_connection_errors(
        self, adapter, session
    ):
        """Polling returns connection error after max retries."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.ConnectError("Connection refused")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                    max_polls=10,
                )
            )

        assert result["success"] is False
        assert "connection failed" in result["error"].lower()
        # Should stop after 3 connection errors (max_connection_errors)
        assert mock_client.get.call_count == 3

    def test_poll_fails_after_repeated_timeout_errors(
        self, adapter, session
    ):
        """Polling returns timeout error after max retries."""
        import httpx

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(
            side_effect=httpx.TimeoutException("Request timed out")
        )
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                    max_polls=10,
                )
            )

        assert result["success"] is False
        assert "timeout" in result["error"].lower()
        assert mock_client.get.call_count == 3

    def test_poll_recovers_from_intermittent_errors(
        self, adapter, session
    ):
        """Polling continues after transient errors and succeeds."""
        import httpx

        responses = [
            httpx.ConnectError("Connection refused"),
            httpx.Response(200, json={"status": "pending"}),
            httpx.Response(
                200,
                json={"status": "completed", "output": "done"},
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                    max_polls=10,
                )
            )

        assert result["status"] == "completed"
        assert result["output"] == "done"


class TestCallbackRegistration:
    """Test webhook callback registration."""

    def test_register_callback_stores_handler(self, adapter, session):
        """register_callback_handler stores the registration."""
        handler_fn = AsyncMock()

        registration = adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        assert isinstance(registration, CallbackRegistration)
        assert registration.callback_url == "http://localhost:8080/webhook"
        assert registration.handler is handler_fn
        assert registration.registered_at is not None
        assert registration.expiry is None
        assert session.session_id in adapter._callback_handlers

    def test_register_callback_with_expiry(self, adapter, session):
        """register_callback_handler accepts an expiry datetime."""
        handler_fn = AsyncMock()
        future_expiry = datetime.now(UTC) + timedelta(hours=1)

        registration = adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
            expiry=future_expiry,
        )

        assert registration.expiry == future_expiry

    def test_register_callback_logs_event(self, adapter, session):
        """register_callback_handler adds a log entry."""
        handler_fn = AsyncMock()

        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        logs = _run(adapter.get_logs(session))
        assert any("Callback registered" in log for log in logs)

    def test_callback_registration_dataclass(self):
        """CallbackRegistration dataclass has expected fields."""
        handler = AsyncMock()
        now = datetime.now(UTC)
        expiry = now + timedelta(hours=2)

        reg = CallbackRegistration(
            callback_url="http://example.com/hook",
            handler=handler,
            registered_at=now,
            expiry=expiry,
        )

        assert reg.callback_url == "http://example.com/hook"
        assert reg.handler is handler
        assert reg.registered_at == now
        assert reg.expiry == expiry


class TestCallbackHandlerInvocation:
    """Test _handle_callback_result invocation."""

    def test_handle_callback_invokes_handler(self, adapter, session):
        """_handle_callback_result calls the registered handler."""
        handler_fn = AsyncMock()

        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        result_data = {
            "session_id": session.session_id,
            "output": "webhook result",
            "success": True,
        }

        handled = _run(
            adapter._handle_callback_result("task-abc", result_data)
        )

        assert handled is True
        handler_fn.assert_called_once_with("task-abc", result_data)

    def test_handle_callback_stores_pending_result(
        self, adapter, session
    ):
        """_handle_callback_result stores result in pending_results."""
        handler_fn = AsyncMock()

        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        result_data = {
            "session_id": session.session_id,
            "output": "stored result",
        }

        _run(
            adapter._handle_callback_result("task-xyz", result_data)
        )

        assert "task-xyz" in adapter._pending_results
        assert adapter._pending_results["task-xyz"]["output"] == "stored result"

    def test_handle_callback_returns_false_no_handler(self, adapter):
        """_handle_callback_result returns False if no handler registered."""
        result_data = {"session_id": "unknown-session", "output": "data"}

        handled = _run(
            adapter._handle_callback_result("task-abc", result_data)
        )

        assert handled is False

    def test_handle_callback_rejects_expired_registration(
        self, adapter, session
    ):
        """_handle_callback_result returns False for expired registrations."""
        handler_fn = AsyncMock()
        past_expiry = datetime.now(UTC) - timedelta(hours=1)

        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
            expiry=past_expiry,
        )

        result_data = {
            "session_id": session.session_id,
            "output": "late result",
        }

        handled = _run(
            adapter._handle_callback_result("task-abc", result_data)
        )

        assert handled is False
        handler_fn.assert_not_called()

    def test_handle_callback_logs_event(self, adapter, session):
        """_handle_callback_result adds a log entry on success."""
        handler_fn = AsyncMock()

        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        result_data = {
            "session_id": session.session_id,
            "output": "result",
        }

        _run(
            adapter._handle_callback_result("task-log", result_data)
        )

        logs = _run(adapter.get_logs(session))
        assert any("Callback received" in log for log in logs)


class TestConfigurablePollParameters:
    """Test that poll parameters are configurable."""

    def test_custom_poll_interval(self, adapter, session):
        """poll_interval parameter controls sleep duration."""
        import httpx

        poll_responses = [
            httpx.Response(
                200,
                json={"status": "completed", "output": "fast"},
            ),
        ]

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=poll_responses)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.001,
                )
            )

        assert result["output"] == "fast"

    def test_custom_max_polls(self, adapter, session):
        """max_polls parameter limits poll iterations."""
        import httpx

        pending_response = httpx.Response(
            200, json={"status": "pending"}
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=pending_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                    max_polls=5,
                )
            )

        assert result["success"] is False
        assert mock_client.get.call_count == 5

    def test_custom_timeout_parameter(self, adapter, session):
        """timeout parameter is passed to derived max_polls."""
        import httpx

        pending_response = httpx.Response(
            200, json={"status": "pending"}
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=pending_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        # timeout=0.1, poll_interval=0.01 -> max_polls = 10
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter._poll_for_result(
                    session,
                    "https://test-agent.example.com/poll/123",
                    poll_interval=0.01,
                    timeout=0.1,
                )
            )

        assert result["success"] is False
        assert mock_client.get.call_count == 10


class TestCapabilities:
    """Test adapter capabilities include webhook_callback."""

    def test_capabilities_include_webhook_callback(self, adapter, session):
        """get_capabilities includes webhook_callback."""
        caps = _run(adapter.get_capabilities(session))
        assert "webhook_callback" in caps

    def test_capabilities_include_standard_features(
        self, adapter, session
    ):
        """get_capabilities includes all expected capabilities."""
        caps = _run(adapter.get_capabilities(session))
        assert "execute_task" in caps
        assert "webhook_polling" in caps
        assert "health_check" in caps
        assert "payload_transformation" in caps
        assert "response_mapping" in caps


class TestFullExecuteWith202:
    """Test full execute_task flow with 202 async response."""

    def test_execute_202_triggers_polling(
        self, adapter, session, task_id
    ):
        """execute_task with 202 response triggers polling."""
        import httpx

        initial_response = httpx.Response(
            202,
            json={
                "poll_url": "https://test-agent.example.com/poll/123",
                "status": "accepted",
            },
        )
        poll_response = httpx.Response(
            200,
            json={
                "status": "completed",
                "output": "async result",
                "success": True,
            },
        )

        call_count = {"value": 0}

        async def mock_post(*args, **kwargs):
            return initial_response

        async def mock_get(*args, **kwargs):
            call_count["value"] += 1
            if call_count["value"] == 1:
                return httpx.Response(
                    200, json={"status": "pending"}
                )
            return poll_response

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=mock_post)
        mock_client.get = AsyncMock(side_effect=mock_get)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = _run(
                adapter.execute_task(
                    session, task_id, {"prompt": "do something"}
                )
            )

        assert result.success is True
        assert result.output == "async result"


class TestTerminateCleanup:
    """Test that terminate cleans up callback handlers."""

    def test_terminate_removes_callback_handlers(
        self, adapter, session
    ):
        """terminate removes callback registrations for the session."""
        handler_fn = AsyncMock()
        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        assert session.session_id in adapter._callback_handlers

        _run(adapter.terminate(session))

        assert session.session_id not in adapter._callback_handlers
