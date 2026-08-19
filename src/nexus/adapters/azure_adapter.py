"""Azure OpenAI Adapter - implements AgentAdapter Protocol for Azure-hosted OpenAI models.

Supports GPT-4o, GPT-4 Turbo, and GPT-3.5 Turbo deployed on Azure OpenAI Service.
Uses async httpx for API communication with retry logic for rate limits.
"""

import asyncio
import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult


# Per-model pricing in cents per 1K tokens (input, output) - Azure pricing
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.25, 1.0),
    "gpt-4-turbo": (1.0, 3.0),
    "gpt-35-turbo": (0.05, 0.15),
}

# Default max retries for rate limit errors
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0

# Maximum number of messages to retain in conversation history per session
MAX_HISTORY_MESSAGES = 50


class AzureOpenAIAdapter(BaseAdapter):
    """Agent adapter for Azure-hosted OpenAI chat completion models.

    Implements the full AgentAdapter Protocol using async httpx to
    communicate with the Azure OpenAI Service. Supports function calling,
    token counting, cost tracking, and exponential backoff on rate limits.
    """

    adapter_type: str = "azure_openai"

    def __init__(self) -> None:
        """Initialize the Azure OpenAI adapter."""
        super().__init__()

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required Azure OpenAI configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If required keys are missing.
        """
        if "api_key" not in config:
            raise ValueError("Azure OpenAI adapter requires 'api_key' in config")
        if "model" not in config:
            raise ValueError("Azure OpenAI adapter requires 'model' in config")
        if "azure_endpoint" not in config:
            raise ValueError("Azure OpenAI adapter requires 'azure_endpoint' in config")
        if "api_version" not in config:
            raise ValueError("Azure OpenAI adapter requires 'api_version' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Azure OpenAI session with conversation history.

        Sets up the system prompt from agent config if provided.

        Args:
            session: The newly created session.
        """
        system_prompt = session.config.get("system_prompt", "")
        if system_prompt:
            self._conversation_history[session.session_id] = [
                {"role": "system", "content": system_prompt}
            ]

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via Azure OpenAI chat completions API.

        Sends the task prompt as a user message, handles function calling
        if tools are specified, and applies retry with exponential backoff
        on rate limit (429) responses.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'tools', 'temperature'.

        Returns:
            TaskResult with the model's response and usage metrics.
        """
        import httpx

        prompt = payload.get("prompt", "")
        tools = payload.get("tools", None)
        temperature = payload.get("temperature", 0.7)
        max_tokens = payload.get("max_tokens", 4096)

        api_key = session.config["api_key"]
        model = session.config["model"]
        azure_endpoint = session.config["azure_endpoint"]
        api_version = session.config["api_version"]

        # Add user message to conversation history
        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "content": prompt})

        # Build request payload
        request_body: dict[str, Any] = {
            "messages": history,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"

        headers = {
            "api-key": api_key,
            "Content-Type": "application/json",
        }

        url = (
            f"https://{azure_endpoint}/openai/deployments/{model}"
            f"/chat/completions?api-version={api_version}"
        )

        # Retry with exponential backoff on rate limits
        response_data: dict[str, Any] = {}
        async with httpx.AsyncClient(timeout=120.0) as client:
            for attempt in range(MAX_RETRIES):
                response = await client.post(
                    url,
                    json=request_body,
                    headers=headers,
                )

                if response.status_code == 429:
                    wait_time = BASE_BACKOFF_SECONDS * (2**attempt)
                    self._add_log(
                        session.session_id,
                        f"Rate limited (429), retrying in {wait_time}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})",
                    )
                    await asyncio.sleep(wait_time)
                    continue

                if response.status_code != 200:
                    error_text = response.text
                    return TaskResult(
                        task_id=task_id,
                        agent_id=session.agent_id,
                        success=False,
                        error=f"Azure OpenAI API error {response.status_code}: {error_text}",
                    )

                response_data = response.json()
                break
            else:
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error="Max retries exceeded due to rate limiting",
                )

        # Parse response
        choices = response_data.get("choices", [])
        usage = response_data.get("usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)

        # Calculate cost
        pricing = MODEL_PRICING.get(model, (0.5, 1.5))
        cost_cents = round(
            (input_tokens / 1000 * pricing[0])
            + (output_tokens / 1000 * pricing[1])
        )

        output_content = ""
        tool_calls = []
        if choices:
            message = choices[0].get("message", {})
            output_content = message.get("content", "")
            tool_calls = message.get("tool_calls", [])
            # Add assistant response to history
            history.append(message)

        # Cap conversation history to prevent unbounded growth
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
        self._conversation_history[session.session_id] = history

        # Build artifacts from tool calls
        artifacts = []
        if tool_calls:
            for tc in tool_calls:
                artifacts.append({
                    "type": "tool_call",
                    "tool_call_id": tc.get("id", ""),
                    "function": tc.get("function", {}),
                })

        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=True,
            output=output_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            artifacts=artifacts,
            logs=[f"Model: {model}, Tokens: {input_tokens}+{output_tokens}"],
        )

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Verify Azure OpenAI session is alive.

        Args:
            session: The active agent session.

        Returns:
            True (Azure OpenAI sessions are stateless, always alive).
        """
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up Azure OpenAI session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Azure OpenAI adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "function_calling",
            "conversation_history",
            "system_prompt",
            "retry_on_rate_limit",
        ]
