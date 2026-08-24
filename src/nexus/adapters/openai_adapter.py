"""OpenAI Adapter - implements AgentAdapter Protocol for OpenAI models.

Supports GPT-4o, o1, o3, and other OpenAI chat completion models.
Uses async httpx for API communication with retry logic for rate limits.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult


# Per-model pricing in cents per 1K tokens (input, output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (0.25, 1.0),
    "gpt-4o-mini": (0.015, 0.06),
    "gpt-4-turbo": (1.0, 3.0),
    "gpt-4": (3.0, 6.0),
    "gpt-3.5-turbo": (0.05, 0.15),
    "o1": (1.5, 6.0),
    "o1-mini": (0.3, 1.2),
    "o3": (1.5, 6.0),
    "o3-mini": (0.11, 0.44),
}

# Default max retries for rate limit errors
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0


class OpenAIAdapter(BaseAdapter):
    """Agent adapter for OpenAI chat completion models.

    Implements the full AgentAdapter Protocol using async httpx to
    communicate with the OpenAI API. Supports function calling, streaming,
    token counting, cost tracking, and exponential backoff on rate limits.
    """

    adapter_type: str = "openai"

    def __init__(self) -> None:
        """Initialize the OpenAI adapter."""
        super().__init__()
        self._api_base = "https://api.openai.com/v1"

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required OpenAI configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If 'api_key' or 'model' is missing.
        """
        if "api_key" not in config:
            raise ValueError("OpenAI adapter requires 'api_key' in config")
        if "model" not in config:
            raise ValueError("OpenAI adapter requires 'model' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize OpenAI session with conversation history.

        Sets up the system prompt from agent config if provided.

        Args:
            session: The newly created session.
        """
        system_prompt = session.config.get("system_prompt", "")
        if system_prompt:
            self._conversation_history[session.session_id] = [
                {"role": "system", "content": system_prompt}
            ]
        # Store API base override if specified
        if "api_base" in session.config:
            session.metadata["api_base"] = session.config["api_base"]

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via OpenAI chat completions API.

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
        stream = payload.get("stream", False)

        api_key = session.config["api_key"]
        model = session.config["model"]
        api_base = session.metadata.get("api_base", self._api_base)

        # Add user message to conversation history
        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "content": prompt})

        # Build request payload
        request_body: dict[str, Any] = {
            "model": model,
            "messages": history,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if stream:
            request_body["stream"] = True
        if tools:
            request_body["tools"] = tools
            request_body["tool_choice"] = "auto"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # Retry with exponential backoff on rate limits
        response_data: dict[str, Any] = {}
        for attempt in range(MAX_RETRIES):
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{api_base}/chat/completions",
                    json=request_body,
                    headers=headers,
                )

            if response.status_code == 429:
                # Rate limited - exponential backoff
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
                    error=f"OpenAI API error {response.status_code}: {error_text}",
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
        cost_cents = int(
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
        """Verify OpenAI session is alive by checking models endpoint.

        Args:
            session: The active agent session.

        Returns:
            True (OpenAI sessions are stateless, always alive).
        """
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up OpenAI session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return OpenAI adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "function_calling",
            "streaming",
            "tool_use",
            "conversation_history",
            "system_prompt",
            "retry_on_rate_limit",
        ]

    async def stream_execute(
        self,
        session: AgentSession,
        task_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> "AsyncGenerator[str, None]":
        """Stream tokens from OpenAI Chat Completions API using SSE.

        Yields text chunks as they arrive from OpenAI's streaming endpoint.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'max_tokens', 'temperature'.

        Yields:
            Individual text chunks as they arrive.
        """
        import json
        import httpx
        from collections.abc import AsyncGenerator

        prompt = payload.get("prompt", "")
        temperature = payload.get("temperature", 0.7)
        max_tokens = payload.get("max_tokens", 4096)

        api_key = session.config["api_key"]
        model = session.config["model"]
        api_base = session.metadata.get("api_base", self._api_base)

        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "content": prompt})

        request_body: dict[str, Any] = {
            "model": model,
            "messages": history,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        accumulated_text = ""

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{api_base}/chat/completions",
                json=request_body,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    yield f"[Error: OpenAI API {response.status_code}]"
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:].strip()
                    if data == "[DONE]":
                        break

                    try:
                        event = json.loads(data)
                        choices = event.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                accumulated_text += content
                                yield content
                    except Exception:
                        continue

        if accumulated_text:
            history.append({"role": "assistant", "content": accumulated_text})
            self._conversation_history[session.session_id] = history
