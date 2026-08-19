"""Tests for additional LLM Provider Adapters (Azure, Bedrock, Gemini).

Tests cover:
- Configuration validation (missing required keys, valid config)
- Session creation with system prompt
- Successful execution with mocked httpx response
- Rate limit (429) retry handling
- Error response handling
- Capability advertisement
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.adapters.azure_adapter import AzureOpenAIAdapter
from nexus.adapters.bedrock_adapter import BedrockAdapter
from nexus.adapters.google_adapter import GoogleGeminiAdapter
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# --- Azure OpenAI Adapter Tests ---


class TestAzureOpenAIAdapterConfig:
    """Test Azure OpenAI adapter configuration validation."""

    @pytest.fixture
    def adapter(self):
        """Create an AzureOpenAIAdapter instance."""
        return AzureOpenAIAdapter()

    def test_missing_api_key_raises(self, adapter):
        """validate_config raises when api_key is missing."""
        with pytest.raises(ValueError, match="api_key"):
            adapter.validate_config({
                "model": "gpt-4o",
                "azure_endpoint": "myresource.openai.azure.com",
                "api_version": "2024-02-01",
            })

    def test_missing_model_raises(self, adapter):
        """validate_config raises when model is missing."""
        with pytest.raises(ValueError, match="model"):
            adapter.validate_config({
                "api_key": "test-key",
                "azure_endpoint": "myresource.openai.azure.com",
                "api_version": "2024-02-01",
            })

    def test_missing_azure_endpoint_raises(self, adapter):
        """validate_config raises when azure_endpoint is missing."""
        with pytest.raises(ValueError, match="azure_endpoint"):
            adapter.validate_config({
                "api_key": "test-key",
                "model": "gpt-4o",
                "api_version": "2024-02-01",
            })

    def test_missing_api_version_raises(self, adapter):
        """validate_config raises when api_version is missing."""
        with pytest.raises(ValueError, match="api_version"):
            adapter.validate_config({
                "api_key": "test-key",
                "model": "gpt-4o",
                "azure_endpoint": "myresource.openai.azure.com",
            })

    def test_valid_config_passes(self, adapter):
        """validate_config succeeds with all required keys."""
        adapter.validate_config({
            "api_key": "test-key",
            "model": "gpt-4o",
            "azure_endpoint": "myresource.openai.azure.com",
            "api_version": "2024-02-01",
        })


class TestAzureOpenAIAdapterSession:
    """Test Azure OpenAI adapter session creation and execution."""

    @pytest.fixture
    def adapter(self):
        """Create an AzureOpenAIAdapter instance."""
        return AzureOpenAIAdapter()

    @pytest.fixture
    def config(self):
        """Valid Azure OpenAI config."""
        return {
            "api_key": "test-azure-key",
            "model": "gpt-4o",
            "azure_endpoint": "myresource.openai.azure.com",
            "api_version": "2024-02-01",
            "system_prompt": "You are a helpful assistant.",
        }

    def test_create_session_stores_system_prompt(self, adapter, config):
        """create_session stores system prompt in conversation history."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        history = adapter._conversation_history.get(session.session_id, [])
        assert len(history) == 1
        assert history[0]["role"] == "system"
        assert history[0]["content"] == "You are a helpful assistant."

    @patch("httpx.AsyncClient")
    def test_execute_success(self, mock_client_cls, adapter, config):
        """_do_execute returns success on 200 response."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": "Hello!", "tool_calls": []}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is True
        assert result.output == "Hello!"
        assert result.input_tokens == 10
        assert result.output_tokens == 5

    @patch("httpx.AsyncClient")
    def test_execute_rate_limit_retry(self, mock_client_cls, adapter, config):
        """_do_execute retries on 429 and succeeds after retry."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.text = "Rate limited"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "choices": [{"message": {"content": "After retry"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_429, mock_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is True
        assert result.output == "After retry"

    @patch("httpx.AsyncClient")
    def test_execute_error_response(self, mock_client_cls, adapter, config):
        """_do_execute returns failure on non-200/429 response."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is False
        assert "500" in result.error

    def test_get_capabilities(self, adapter):
        """Azure OpenAI adapter reports expected capabilities."""
        caps = adapter._get_capabilities()
        assert "execute_task" in caps
        assert "function_calling" in caps
        assert "conversation_history" in caps
        assert "system_prompt" in caps
        assert "retry_on_rate_limit" in caps


# --- AWS Bedrock Adapter Tests ---


class TestBedrockAdapterConfig:
    """Test Bedrock adapter configuration validation."""

    @pytest.fixture
    def adapter(self):
        """Create a BedrockAdapter instance."""
        return BedrockAdapter()

    def test_missing_access_key_raises(self, adapter):
        """validate_config raises when aws_access_key_id is missing."""
        with pytest.raises(ValueError, match="aws_access_key_id"):
            adapter.validate_config({
                "aws_secret_access_key": "secret",
                "region": "us-east-1",
                "model": "anthropic.claude-3-5-sonnet",
            })

    def test_missing_secret_key_raises(self, adapter):
        """validate_config raises when aws_secret_access_key is missing."""
        with pytest.raises(ValueError, match="aws_secret_access_key"):
            adapter.validate_config({
                "aws_access_key_id": "AKID",
                "region": "us-east-1",
                "model": "anthropic.claude-3-5-sonnet",
            })

    def test_missing_region_raises(self, adapter):
        """validate_config raises when region is missing."""
        with pytest.raises(ValueError, match="region"):
            adapter.validate_config({
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "secret",
                "model": "anthropic.claude-3-5-sonnet",
            })

    def test_missing_model_raises(self, adapter):
        """validate_config raises when model is missing."""
        with pytest.raises(ValueError, match="model"):
            adapter.validate_config({
                "aws_access_key_id": "AKID",
                "aws_secret_access_key": "secret",
                "region": "us-east-1",
            })

    def test_valid_config_passes(self, adapter):
        """validate_config succeeds with all required keys."""
        adapter.validate_config({
            "aws_access_key_id": "AKID",
            "aws_secret_access_key": "secret",
            "region": "us-east-1",
            "model": "anthropic.claude-3-5-sonnet",
        })


class TestBedrockAdapterSession:
    """Test Bedrock adapter session creation and execution."""

    @pytest.fixture
    def adapter(self):
        """Create a BedrockAdapter instance."""
        return BedrockAdapter()

    @pytest.fixture
    def config(self):
        """Valid Bedrock config."""
        return {
            "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
            "aws_secret_access_key": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "region": "us-east-1",
            "model": "anthropic.claude-3-5-sonnet",
            "system_prompt": "You are a research assistant.",
        }

    def test_create_session_stores_system_prompt(self, adapter, config):
        """create_session stores system prompt in session metadata."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        assert session.metadata["system_prompt"] == "You are a research assistant."

    @patch("httpx.AsyncClient")
    def test_execute_success(self, mock_client_cls, adapter, config):
        """_do_execute returns success on 200 response."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": "Hello from Claude!"}],
            "usage": {"input_tokens": 15, "output_tokens": 8},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        result = _run(adapter.execute_task(session, task_id, {"prompt": "Hello"}))

        assert result.success is True
        assert result.output == "Hello from Claude!"
        assert result.input_tokens == 15
        assert result.output_tokens == 8

    @patch("httpx.AsyncClient")
    def test_execute_rate_limit_retry(self, mock_client_cls, adapter, config):
        """_do_execute retries on 429 and succeeds after retry."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.text = "Too many requests"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "content": [{"type": "text", "text": "Retry success"}],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_429, mock_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is True
        assert result.output == "Retry success"

    @patch("httpx.AsyncClient")
    def test_execute_error_response(self, mock_client_cls, adapter, config):
        """_do_execute returns failure on non-200/429 response."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "Access Denied"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is False
        assert "403" in result.error

    def test_get_capabilities(self, adapter):
        """Bedrock adapter reports expected capabilities."""
        caps = adapter._get_capabilities()
        assert "execute_task" in caps
        assert "conversation_history" in caps
        assert "system_prompt" in caps
        assert "retry_on_rate_limit" in caps


# --- Google Gemini Adapter Tests ---


class TestGoogleGeminiAdapterConfig:
    """Test Google Gemini adapter configuration validation."""

    @pytest.fixture
    def adapter(self):
        """Create a GoogleGeminiAdapter instance."""
        return GoogleGeminiAdapter()

    def test_missing_api_key_raises(self, adapter):
        """validate_config raises when api_key is missing."""
        with pytest.raises(ValueError, match="api_key"):
            adapter.validate_config({"model": "gemini-2.0-flash"})

    def test_missing_model_raises(self, adapter):
        """validate_config raises when model is missing."""
        with pytest.raises(ValueError, match="model"):
            adapter.validate_config({"api_key": "test-key"})

    def test_valid_config_passes(self, adapter):
        """validate_config succeeds with all required keys."""
        adapter.validate_config({
            "api_key": "test-gemini-key",
            "model": "gemini-2.0-flash",
        })


class TestGoogleGeminiAdapterSession:
    """Test Google Gemini adapter session creation and execution."""

    @pytest.fixture
    def adapter(self):
        """Create a GoogleGeminiAdapter instance."""
        return GoogleGeminiAdapter()

    @pytest.fixture
    def config(self):
        """Valid Google Gemini config."""
        return {
            "api_key": "test-gemini-key",
            "model": "gemini-2.0-flash",
            "system_prompt": "You are a coding assistant.",
        }

    def test_create_session_stores_system_prompt(self, adapter, config):
        """create_session stores system prompt in session metadata."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        assert session.metadata["system_prompt"] == "You are a coding assistant."

    @patch("httpx.AsyncClient")
    def test_execute_success(self, mock_client_cls, adapter, config):
        """_do_execute returns success on 200 response."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Hello from Gemini!"}],
                    "role": "model",
                }
            }],
            "usageMetadata": {
                "promptTokenCount": 12,
                "candidatesTokenCount": 6,
            },
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        result = _run(adapter.execute_task(session, task_id, {"prompt": "Hello"}))

        assert result.success is True
        assert result.output == "Hello from Gemini!"
        assert result.input_tokens == 12
        assert result.output_tokens == 6

    @patch("httpx.AsyncClient")
    def test_execute_rate_limit_retry(self, mock_client_cls, adapter, config):
        """_do_execute retries on 429 and succeeds after retry."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.text = "Resource exhausted"

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "After retry"}],
                    "role": "model",
                }
            }],
            "usageMetadata": {
                "promptTokenCount": 8,
                "candidatesTokenCount": 4,
            },
        }

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=[mock_429, mock_200])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is True
        assert result.output == "After retry"

    @patch("httpx.AsyncClient")
    def test_execute_error_response(self, mock_client_cls, adapter, config):
        """_do_execute returns failure on non-200/429 response."""
        agent_id = uuid.uuid4()
        session = _run(adapter.create_session(agent_id, config))

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad Request"

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client_cls.return_value = mock_client

        task_id = uuid.uuid4()
        result = _run(adapter.execute_task(session, task_id, {"prompt": "Hi"}))

        assert result.success is False
        assert "400" in result.error

    def test_get_capabilities(self, adapter):
        """Google Gemini adapter reports expected capabilities."""
        caps = adapter._get_capabilities()
        assert "execute_task" in caps
        assert "function_calling" in caps
        assert "conversation_history" in caps
        assert "system_prompt" in caps
        assert "retry_on_rate_limit" in caps

    def test_adapter_type(self, adapter):
        """Google Gemini adapter has correct adapter_type."""
        assert adapter.adapter_type == "google_gemini"
