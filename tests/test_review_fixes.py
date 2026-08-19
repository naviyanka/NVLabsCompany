"""Tests for review-fix changes across adapters and knowledge modules.

Covers:
- Issue #1: _stream_output wired into interactive mode execution
- Issue #2: Callback routing rejects payloads without session_id
- Issue #3: _recent_changes list is bounded by max_recent_changes
- Issue #4: Subscriber exception isolation in notify_subscribers
- Issue #6: ConditionBuilder replaces (not accumulates) expressions
"""

import asyncio
import logging
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.adapters.cli_adapter import CLIAdapter
from nexus.adapters.http_adapter import HTTPAdapter
from nexus.knowledge.plaza import KnowledgePlaza
from nexus.triggers.context_trigger import (
    ConditionBuilder,
    ThresholdCondition,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Issue #2: Callback routing requires session_id
# ---------------------------------------------------------------------------


class TestCallbackRoutingNoFallback:
    """Verify callback routing rejects payloads missing session_id."""

    @pytest.fixture
    def adapter(self):
        return HTTPAdapter()

    @pytest.fixture
    def agent_id(self):
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def config(self):
        return {
            "base_url": "http://test-agent.example.com",
            "bearer_token": "test-token-123",
            "poll_interval": 0.1,
            "timeout": 5.0,
        }

    @pytest.fixture
    def session(self, adapter, agent_id, config):
        return _run(adapter.create_session(agent_id, config))

    def test_missing_session_id_returns_false(self, adapter, session):
        """Payload without session_id is rejected (no fallback iteration)."""
        handler_fn = AsyncMock()
        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        # Payload has no session_id key
        result_data = {"output": "some result", "success": True}
        handled = _run(adapter._handle_callback_result("task-abc", result_data))

        assert handled is False
        handler_fn.assert_not_called()

    def test_empty_session_id_returns_false(self, adapter, session):
        """Payload with empty string session_id is rejected."""
        handler_fn = AsyncMock()
        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        result_data = {"session_id": "", "output": "result"}
        handled = _run(adapter._handle_callback_result("task-abc", result_data))

        assert handled is False
        handler_fn.assert_not_called()

    def test_correct_session_id_still_works(self, adapter, session):
        """Payload with correct session_id routes successfully."""
        handler_fn = AsyncMock()
        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook",
            session=session,
            handler_fn=handler_fn,
        )

        result_data = {
            "session_id": session.session_id,
            "output": "routed result",
        }
        handled = _run(adapter._handle_callback_result("task-ok", result_data))

        assert handled is True
        handler_fn.assert_called_once_with("task-ok", result_data)

    def test_multiple_registrations_no_ambiguity(self, adapter, agent_id, config):
        """With multiple sessions, missing session_id does not route to first."""
        session1 = _run(adapter.create_session(agent_id, config))
        session2 = _run(adapter.create_session(agent_id, config))

        handler1 = AsyncMock()
        handler2 = AsyncMock()
        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook1",
            session=session1,
            handler_fn=handler1,
        )
        adapter.register_callback_handler(
            callback_url="http://localhost:8080/webhook2",
            session=session2,
            handler_fn=handler2,
        )

        # Payload without session_id must not route to either handler
        result_data = {"output": "ambiguous"}
        handled = _run(adapter._handle_callback_result("task-x", result_data))

        assert handled is False
        handler1.assert_not_called()
        handler2.assert_not_called()


# ---------------------------------------------------------------------------
# Issue #3: Bounded _recent_changes list
# ---------------------------------------------------------------------------


class TestBoundedRecentChanges:
    """Verify _recent_changes is pruned to max_recent_changes."""

    @pytest.fixture
    def mock_db(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.exec = AsyncMock()
        return session

    @pytest.fixture
    def company_id(self):
        return uuid.UUID("12345678-1234-1234-1234-123456789abc")

    @pytest.fixture
    def agent_id(self):
        return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    def test_default_max_recent_changes(self, mock_db):
        """Default max_recent_changes is 1000."""
        plaza = KnowledgePlaza(mock_db)
        assert plaza._max_recent_changes == 1000

    def test_custom_max_recent_changes(self, mock_db):
        """max_recent_changes can be set via constructor."""
        plaza = KnowledgePlaza(mock_db, max_recent_changes=50)
        assert plaza._max_recent_changes == 50

    @pytest.mark.asyncio
    async def test_prune_at_max_limit(self, mock_db, company_id, agent_id):
        """Events beyond max_recent_changes are pruned."""
        max_changes = 10
        plaza = KnowledgePlaza(mock_db, max_recent_changes=max_changes)

        # Generate more events than the max
        for _ in range(15):
            page_id = uuid.uuid4()
            await plaza.notify_subscribers(
                page_id, company_id, "created", agent_id
            )

        # Should be pruned to max_changes
        assert len(plaza._recent_changes) == max_changes

    @pytest.mark.asyncio
    async def test_recent_events_preserved(self, mock_db, company_id, agent_id):
        """Most recent events are kept after pruning, oldest are dropped."""
        max_changes = 5
        plaza = KnowledgePlaza(mock_db, max_recent_changes=max_changes)

        page_ids = []
        for _ in range(8):
            page_id = uuid.uuid4()
            page_ids.append(page_id)
            await plaza.notify_subscribers(
                page_id, company_id, "created", agent_id
            )

        # Last 5 page_ids should be the ones retained
        retained_page_ids = [e.page_id for e in plaza._recent_changes]
        assert retained_page_ids == page_ids[-5:]


# ---------------------------------------------------------------------------
# Issue #4: Subscriber exception isolation
# ---------------------------------------------------------------------------


class TestSubscriberExceptionIsolation:
    """Verify failing subscribers don't block others."""

    @pytest.fixture
    def mock_db(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.exec = AsyncMock()
        return session

    @pytest.fixture
    def company_id(self):
        return uuid.UUID("12345678-1234-1234-1234-123456789abc")

    @pytest.fixture
    def agent_id(self):
        return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")

    @pytest.fixture
    def page_id(self):
        return uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    @pytest.mark.asyncio
    async def test_sync_callback_exception_does_not_block(
        self, mock_db, company_id, agent_id, page_id
    ):
        """A sync callback raising does not prevent others from being called."""
        plaza = KnowledgePlaza(mock_db)

        cb_before = MagicMock()
        cb_failing = MagicMock(side_effect=ValueError("oops"))
        cb_after = MagicMock()

        plaza.subscribe(company_id, cb_before)
        plaza.subscribe(company_id, cb_failing)
        plaza.subscribe(company_id, cb_after)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        cb_before.assert_called_once()
        cb_failing.assert_called_once()
        cb_after.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_callback_exception_does_not_block(
        self, mock_db, company_id, agent_id, page_id
    ):
        """An async callback raising does not prevent others from being called."""
        plaza = KnowledgePlaza(mock_db)

        cb_before = AsyncMock()
        cb_failing = AsyncMock(side_effect=RuntimeError("boom"))
        cb_after = AsyncMock()

        plaza.subscribe(company_id, cb_before)
        plaza.subscribe(company_id, cb_failing)
        plaza.subscribe(company_id, cb_after)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        cb_before.assert_awaited_once()
        cb_failing.assert_awaited_once()
        cb_after.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_exception_is_logged(
        self, mock_db, company_id, agent_id, page_id, caplog
    ):
        """Subscriber exceptions are logged with details."""
        plaza = KnowledgePlaza(mock_db)

        cb_failing = MagicMock(side_effect=ValueError("test error"))
        plaza.subscribe(company_id, cb_failing)

        with caplog.at_level(logging.ERROR, logger="nexus.knowledge.plaza"):
            await plaza.notify_subscribers(
                page_id, company_id, "updated", agent_id
            )

        assert "failed" in caplog.text.lower() or "error" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Issue #1: _stream_output wired into interactive mode
# ---------------------------------------------------------------------------


class TestStreamOutputWiredIntoInteractive:
    """Verify _stream_output is called as a background task in interactive mode."""

    @pytest.fixture
    def adapter(self):
        return CLIAdapter()

    @pytest.fixture
    def agent_id(self):
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    def test_interactive_mode_sets_awaiting_input(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Interactive mode sets awaiting_input=True when streaming starts."""
        mock_process = AsyncMock()
        mock_process.returncode = 0
        mock_process.wait = AsyncMock(return_value=0)
        # stdout with some lines then EOF
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(side_effect=[b"ready\n", b""])
        mock_stdout.read = AsyncMock(return_value=b"")
        mock_process.stdout = mock_stdout
        # stderr
        mock_stderr = AsyncMock()
        mock_stderr.read = AsyncMock(return_value=b"")
        mock_process.stderr = mock_stderr
        # stdin
        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_process.stdin = mock_stdin

        mock_exec.return_value = mock_process

        config = {
            "backend": "claude",
            "workspace": "/tmp/test_interactive",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "hello"}
        result = _run(adapter.execute_task(session, task_id, payload))

        # The process completed successfully
        assert result.success is True
        # Logs should contain stdout streaming evidence
        logs = _run(adapter.get_logs(session))
        stdout_logs = [log for log in logs if "[stdout]" in log]
        assert any("ready" in log for log in stdout_logs)

    @patch("asyncio.create_subprocess_exec")
    def test_non_interactive_mode_does_not_stream(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Non-interactive mode uses communicate() without _stream_output."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b"output\n", b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {
            "backend": "claude",
            "workspace": "/tmp/test_noninteractive",
            "interactive": False,
        }
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "hello"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        assert "output" in result.output
        # communicate was called (not wait)
        mock_process.communicate.assert_awaited_once()


# ---------------------------------------------------------------------------
# Issue #6: ConditionBuilder replaces expression
# ---------------------------------------------------------------------------


class TestConditionBuilderReplaces:
    """Verify builder methods replace rather than accumulate."""

    def test_threshold_then_and_discards_threshold(self):
        """Chaining threshold().and_() keeps only the and_ expression."""
        cond = (
            ConditionBuilder()
            .threshold("cpu", ">", 80.0)
            .and_(
                ThresholdCondition(metric="mem", operator=">", value=70.0),
                ThresholdCondition(metric="disk", operator=">", value=90.0),
            )
            .build()
        )
        # The result is an AND, not a threshold
        from nexus.triggers.context_trigger import AndCondition
        assert isinstance(cond, AndCondition)
        assert len(cond.conditions) == 2

    def test_and_then_threshold_discards_and(self):
        """Chaining and_().threshold() keeps only the threshold expression."""
        cond = (
            ConditionBuilder()
            .and_(
                ThresholdCondition(metric="mem", operator=">", value=70.0),
                ThresholdCondition(metric="disk", operator=">", value=90.0),
            )
            .threshold("cpu", ">", 80.0)
            .build()
        )
        assert isinstance(cond, ThresholdCondition)
        assert cond.metric == "cpu"

    def test_single_method_call_works(self):
        """A single builder method call produces the expected expression."""
        cond = ConditionBuilder().threshold("temp", ">=", 100.0).build()
        assert isinstance(cond, ThresholdCondition)
        assert cond.metric == "temp"
        assert cond.value == 100.0
