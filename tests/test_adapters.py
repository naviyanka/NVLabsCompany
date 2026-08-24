"""Tests for NEXUS Agent Adapters - base adapter logic, registry, factory.

Tests cover:
- BaseAdapter session management lifecycle
- Cost accumulation and tracking
- Artifact collection
- Log buffering
- Error handling in execute_task
- AdapterRegistry registration, creation, listing
- OpenAI and Anthropic config validation
"""

import asyncio
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.adapters.base import BaseAdapter
from nexus.adapters.openai_adapter import OpenAIAdapter
from nexus.adapters.anthropic_adapter import AnthropicAdapter
from nexus.adapters.registry import AdapterRegistry
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# --- Concrete adapter for testing BaseAdapter ---


class ConcreteTestAdapter(BaseAdapter):
    """Minimal concrete adapter for testing BaseAdapter logic."""

    adapter_type: str = "test"

    def __init__(self):
        super().__init__()
        self._execute_result: TaskResult | None = None
        self._execute_raises: Exception | None = None

    def validate_config(self, config: dict) -> None:
        if "required_key" not in config:
            raise ValueError("Missing 'required_key' in config")

    async def _do_execute(self, session, task_id, payload):
        if self._execute_raises:
            raise self._execute_raises
        if self._execute_result:
            return self._execute_result
        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=True,
            output="test output",
            cost_cents=10,
            input_tokens=100,
            output_tokens=50,
            artifacts=[{"type": "code", "path": "/tmp/test.py"}],
            logs=["Step 1 done", "Step 2 done"],
        )


class TestBaseAdapter:
    """Test BaseAdapter session management, cost tracking, and error handling."""

    @pytest.fixture
    def adapter(self):
        """Create a ConcreteTestAdapter instance."""
        return ConcreteTestAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    def test_create_session_populates_tracking(self, adapter, agent_id):
        """create_session initializes all tracking dictionaries."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        assert session.session_id in adapter._sessions
        assert session.session_id in adapter._cost_tracking
        assert session.session_id in adapter._artifacts
        assert session.session_id in adapter._logs
        assert session.agent_id == agent_id
        assert session.adapter_type == "test"
        assert session.status == AgentStatus.READY

    def test_create_session_validates_config(self, adapter, agent_id):
        """create_session raises ValueError for invalid config."""
        with pytest.raises(ValueError, match="Missing 'required_key'"):
            _run(adapter.create_session(agent_id, {"bad_key": "value"}))

    def test_terminate_cleans_up(self, adapter, agent_id):
        """terminate removes session from tracking and sets status."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))
        session_id = session.session_id

        result = _run(adapter.terminate(session))

        assert result is True
        assert session_id not in adapter._sessions
        assert session.status == AgentStatus.TERMINATED

    def test_terminate_already_terminated(self, adapter, agent_id):
        """terminate returns False for unknown session."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))
        _run(adapter.terminate(session))

        # Second terminate should return False
        result = _run(adapter.terminate(session))
        assert result is False

    def test_get_cost_returns_accumulated(self, adapter, agent_id, task_id):
        """get_cost returns accumulated cost after execute_task."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        # Execute task (adds 10 cents, 100 input, 50 output)
        _run(adapter.execute_task(session, task_id, {"prompt": "test"}))

        cost = _run(adapter.get_cost(session))
        assert cost["cost_cents"] == 10
        assert cost["input_tokens"] == 100
        assert cost["output_tokens"] == 50

    def test_cost_accumulates_across_executions(self, adapter, agent_id, task_id):
        """Multiple executions accumulate costs."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        _run(adapter.execute_task(session, task_id, {"prompt": "task1"}))
        _run(adapter.execute_task(session, task_id, {"prompt": "task2"}))

        cost = _run(adapter.get_cost(session))
        assert cost["cost_cents"] == 20
        assert cost["input_tokens"] == 200
        assert cost["output_tokens"] == 100

    def test_get_artifacts_returns_collected(self, adapter, agent_id, task_id):
        """get_artifacts returns artifacts produced during execution."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        _run(adapter.execute_task(session, task_id, {"prompt": "test"}))

        artifacts = _run(adapter.get_artifacts(session))
        assert len(artifacts) == 1
        assert artifacts[0]["type"] == "code"
        assert artifacts[0]["path"] == "/tmp/test.py"

    def test_get_logs_returns_buffered(self, adapter, agent_id, task_id):
        """get_logs returns session and execution logs."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        _run(adapter.execute_task(session, task_id, {"prompt": "test"}))

        logs = _run(adapter.get_logs(session))
        # Should have: session created log, executing log, step 1, step 2, completed log
        assert len(logs) >= 3
        # Check that session creation log is present
        assert any("Session created" in log for log in logs)
        # Check that the execution logs from TaskResult are present
        assert any("Step 1 done" in log for log in logs)
        assert any("Step 2 done" in log for log in logs)

    def test_error_handling_wraps_exceptions(self, adapter, agent_id, task_id):
        """execute_task wraps exceptions in a failed TaskResult."""
        adapter._execute_raises = RuntimeError("something went wrong")
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        result = _run(adapter.execute_task(session, task_id, {"prompt": "test"}))

        assert result.success is False
        assert "RuntimeError" in result.error
        assert "something went wrong" in result.error
        assert session.status == AgentStatus.ERROR

    def test_pause_and_resume(self, adapter, agent_id):
        """pause and resume transition session status correctly."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))
        assert session.status == AgentStatus.READY

        paused = _run(adapter.pause(session))
        assert paused is True
        assert session.status == AgentStatus.PAUSED

        resumed = _run(adapter.resume(session))
        assert resumed is True
        assert session.status == AgentStatus.READY

    def test_pause_invalid_state(self, adapter, agent_id):
        """pause returns False if session is not in a pausable state."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))
        session.status = AgentStatus.TERMINATED

        result = _run(adapter.pause(session))
        assert result is False

    def test_resume_not_paused(self, adapter, agent_id):
        """resume returns False if session is not paused."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        result = _run(adapter.resume(session))
        assert result is False

    def test_heartbeat_active_session(self, adapter, agent_id):
        """send_heartbeat returns True for active sessions."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        result = _run(adapter.send_heartbeat(session))
        assert result is True

    def test_heartbeat_terminated_session(self, adapter, agent_id):
        """send_heartbeat returns False for terminated sessions."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))
        session.status = AgentStatus.TERMINATED

        result = _run(adapter.send_heartbeat(session))
        assert result is False

    def test_get_status(self, adapter, agent_id):
        """get_status returns the current session status."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        status = _run(adapter.get_status(session))
        assert status == AgentStatus.READY

    def test_get_capabilities(self, adapter, agent_id):
        """get_capabilities returns adapter capabilities."""
        config = {"required_key": "value"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))
        assert "execute_task" in caps


class TestAdapterRegistry:
    """Test AdapterRegistry registration, creation, and listing."""

    @pytest.fixture
    def registry(self):
        """Create an AdapterRegistry with auto_register=False."""
        return AdapterRegistry(auto_register=False)

    @pytest.fixture
    def full_registry(self):
        """Create an AdapterRegistry with all defaults registered."""
        return AdapterRegistry(auto_register=True)

    def test_register_adapter_adds_to_registry(self, registry):
        """register_adapter makes the adapter available."""
        registry.register_adapter("test", ConcreteTestAdapter)

        assert registry.is_registered("test")
        assert "test" in registry.get_adapter_types()

    def test_create_adapter_instantiates_correct_type(self, registry):
        """create_adapter returns an instance of the registered class."""
        registry.register_adapter("test", ConcreteTestAdapter)

        adapter = registry.create_adapter("test")

        assert isinstance(adapter, ConcreteTestAdapter)
        assert adapter.adapter_type == "test"

    def test_list_adapters_returns_all_registered(self, registry):
        """get_adapter_types returns all registered adapter names."""
        registry.register_adapter("test1", ConcreteTestAdapter)
        registry.register_adapter("test2", OpenAIAdapter)

        types = registry.get_adapter_types()
        assert "test1" in types
        assert "test2" in types
        assert len(types) == 2

    def test_unknown_adapter_raises_error(self, registry):
        """create_adapter raises ValueError for unregistered type."""
        with pytest.raises(ValueError, match="Unknown adapter type"):
            registry.create_adapter("nonexistent")

    def test_default_adapters_pre_registered(self, full_registry):
        """Auto-registered registry has all 7 default adapters."""
        types = full_registry.get_adapter_types()
        assert "openai" in types
        assert "anthropic" in types
        assert "ollama" in types
        assert "claude_code" in types
        assert "cli" in types
        assert "http" in types
        assert "mcp" in types
        assert len(types) >= 7

    def test_register_non_base_adapter_raises(self, registry):
        """register_adapter raises TypeError for non-BaseAdapter class."""
        with pytest.raises(TypeError, match="must be a subclass of BaseAdapter"):
            registry.register_adapter("bad", dict)  # type: ignore

    def test_unregister_adapter(self, registry):
        """unregister_adapter removes a previously registered adapter."""
        registry.register_adapter("test", ConcreteTestAdapter)
        assert registry.is_registered("test")

        result = registry.unregister_adapter("test")
        assert result is True
        assert not registry.is_registered("test")

    def test_create_adapter_with_config_validation(self, full_registry):
        """create_adapter validates config when provided."""
        with pytest.raises(ValueError, match="api_key"):
            full_registry.create_adapter("openai", config={"model": "gpt-4o"})

    def test_get_capabilities_for_type(self, full_registry):
        """get_capabilities returns capabilities for a registered adapter."""
        caps = full_registry.get_capabilities("openai")
        assert "execute_task" in caps
        assert "function_calling" in caps


class TestOpenAIAdapter:
    """Test OpenAI adapter config validation."""

    @pytest.fixture
    def adapter(self):
        """Create an OpenAIAdapter instance."""
        return OpenAIAdapter()

    def test_missing_api_key_raises(self, adapter):
        """validate_config raises when api_key is missing."""
        with pytest.raises(ValueError, match="api_key"):
            adapter.validate_config({"model": "gpt-4o"})

    def test_missing_model_raises(self, adapter):
        """validate_config raises when model is missing."""
        with pytest.raises(ValueError, match="model"):
            adapter.validate_config({"api_key": "sk-test"})

    def test_valid_config_passes(self, adapter):
        """validate_config succeeds with both required keys."""
        # Should not raise
        adapter.validate_config({"api_key": "sk-test", "model": "gpt-4o"})

    def test_create_session_with_system_prompt(self, adapter):
        """create_session stores system prompt in conversation history."""
        agent_id = uuid.uuid4()
        config = {
            "api_key": "sk-test",
            "model": "gpt-4o",
            "system_prompt": "You are a helpful assistant.",
        }
        session = _run(adapter.create_session(agent_id, config))

        history = adapter._conversation_history.get(session.session_id, [])
        assert len(history) == 1
        assert history[0]["role"] == "system"
        assert history[0]["content"] == "You are a helpful assistant."

    def test_capabilities_include_function_calling(self, adapter):
        """OpenAI adapter reports function_calling capability."""
        agent_id = uuid.uuid4()
        config = {"api_key": "sk-test", "model": "gpt-4o"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))
        assert "function_calling" in caps
        assert "streaming" in caps
        assert "retry_on_rate_limit" in caps


class TestAnthropicAdapter:
    """Test Anthropic adapter config validation."""

    @pytest.fixture
    def adapter(self):
        """Create an AnthropicAdapter instance."""
        return AnthropicAdapter()

    def test_missing_api_key_raises(self, adapter):
        """validate_config raises when api_key is missing."""
        with pytest.raises(ValueError, match="api_key"):
            adapter.validate_config({"model": "claude-3-5-sonnet-20241022"})

    def test_missing_model_raises(self, adapter):
        """validate_config raises when model is missing."""
        with pytest.raises(ValueError, match="model"):
            adapter.validate_config({"api_key": "sk-ant-test"})

    def test_valid_config_passes(self, adapter):
        """validate_config succeeds with both required keys."""
        adapter.validate_config({
            "api_key": "sk-ant-test",
            "model": "claude-3-5-sonnet-20241022",
        })

    def test_create_session_stores_system_prompt(self, adapter):
        """create_session stores system prompt in session metadata."""
        agent_id = uuid.uuid4()
        config = {
            "api_key": "sk-ant-test",
            "model": "claude-3-5-sonnet-20241022",
            "system_prompt": "You are a research analyst.",
        }
        session = _run(adapter.create_session(agent_id, config))

        assert session.metadata["system_prompt"] == "You are a research analyst."

    def test_capabilities_include_tool_use(self, adapter):
        """Anthropic adapter reports tool_use capability."""
        agent_id = uuid.uuid4()
        config = {"api_key": "sk-ant-test", "model": "claude-3-5-sonnet-20241022"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))
        assert "tool_use" in caps
        assert "extended_thinking" in caps
