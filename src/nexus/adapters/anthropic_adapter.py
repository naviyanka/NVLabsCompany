"""Anthropic Adapter - implements AgentAdapter Protocol for Claude models.

Supports Claude 3.5, Claude 3, and other Anthropic models.
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
    "claude-3-5-sonnet-20241022": (0.3, 1.5),
    "claude-3-5-haiku-20241022": (0.08, 0.4),
    "claude-3-opus-20240229": (1.5, 7.5),
    "claude-3-sonnet-20240229": (0.3, 1.5),
    "claude-3-haiku-20240307": (0.025, 0.125),
    "claude-sonnet-4-20250514": (0.3, 1.5),
    "claude-opus-4-20250514": (1.5, 7.5),
}

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0


class AnthropicAdapter(BaseAdapter):
    """Agent adapter for Anthropic Claude models.

    Implements the full AgentAdapter Protocol using async httpx to
    communicate with the Anthropic Messages API. Supports tool use,
    extended thinking, token counting, cost tracking, and exponential
    backoff on rate limits.
    """

    adapter_type: str = "anthropic"

    def __init__(self) -> None:
        """Initialize the Anthropic adapter."""
        super().__init__()
        self._api_base = "https://api.anthropic.com/v1"

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required Anthropic configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If 'api_key' or 'model' is missing.
        """
        if "api_key" not in config:
            raise ValueError("Anthropic adapter requires 'api_key' in config")
        if "model" not in config:
            raise ValueError("Anthropic adapter requires 'model' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Anthropic session with system prompt.

        Args:
            session: The newly created session.
        """
        # Store system prompt separately (Anthropic uses system parameter)
        session.metadata["system_prompt"] = session.config.get(
            "system_prompt", ""
        )
        session.metadata["extended_thinking"] = session.config.get(
            "extended_thinking", False
        )

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via Anthropic Messages API.

        Sends the task prompt as a user message, handles tool use if tools
        are specified, and applies retry with exponential backoff on rate
        limit (429) responses.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'tools', 'max_tokens'.

        Returns:
            TaskResult with the model's response and usage metrics.
        """
        import httpx

        prompt = payload.get("prompt", "")
        tools = payload.get("tools", None)
        max_tokens = payload.get("max_tokens", 4096)

        api_key = session.config["api_key"]
        model = session.config["model"]
        system_prompt = session.metadata.get("system_prompt", "")
        extended_thinking = session.metadata.get("extended_thinking", False)

        # Build messages from conversation history
        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "content": prompt})

        # Build request payload
        request_body: dict[str, Any] = {
            "model": model,
            "messages": history,
            "max_tokens": max_tokens,
        }
        if system_prompt:
            request_body["system"] = system_prompt
        if tools:
            request_body["tools"] = tools
        if extended_thinking:
            request_body["metadata"] = {"extended_thinking": True}

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        # Retry with exponential backoff on rate limits
        response_data: dict[str, Any] = {}
        for attempt in range(MAX_RETRIES):
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self._api_base}/messages",
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
                    error=f"Anthropic API error {response.status_code}: {error_text}",
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

        # Parse Anthropic response content blocks
        content_blocks = response_data.get("content", [])
        usage = response_data.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        # Calculate cost
        pricing = MODEL_PRICING.get(model, (0.3, 1.5))
        cost_cents = int(
            (input_tokens / 1000 * pricing[0])
            + (output_tokens / 1000 * pricing[1])
        )

        # Extract text and tool use from content blocks
        text_parts: list[str] = []
        tool_use_blocks: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []

        for block in content_blocks:
            block_type = block.get("type", "")
            if block_type == "text":
                text_parts.append(block.get("text", ""))
            elif block_type == "tool_use":
                tool_use_blocks.append(block)
                artifacts.append({
                    "type": "tool_use",
                    "tool_use_id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": block.get("input", {}),
                })
            elif block_type == "thinking":
                # Extended thinking block
                artifacts.append({
                    "type": "thinking",
                    "content": block.get("thinking", ""),
                })

        output_content = "\n".join(text_parts)

        # Add assistant response to history
        history.append({"role": "assistant", "content": content_blocks})
        self._conversation_history[session.session_id] = history

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
        """Verify Anthropic session is alive.

        Args:
            session: The active agent session.

        Returns:
            True (Anthropic sessions are stateless, always alive).
        """
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up Anthropic session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Anthropic adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "tool_use",
            "extended_thinking",
            "conversation_history",
            "system_prompt",
            "retry_on_rate_limit",
            "streaming",
        ]

    async def stream_execute(
        self,
        session: AgentSession,
        task_id: uuid.UUID,
        payload: dict[str, Any],
    ) -> "AsyncGenerator[str, None]":
        """Stream tokens from the Anthropic Messages API using SSE.

        Yields text chunks as they arrive from the API's streaming endpoint.
        This provides true token-level streaming instead of simulated word-by-word.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'max_tokens'.

        Yields:
            Individual text chunks (tokens/words) as they arrive.
        """
        import httpx
        from collections.abc import AsyncGenerator

        prompt = payload.get("prompt", "")
        max_tokens = payload.get("max_tokens", 4096)

        api_key = session.config["api_key"]
        model = session.config["model"]
        system_prompt = session.metadata.get("system_prompt", "")

        # Build messages
        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "content": prompt})

        request_body: dict[str, Any] = {
            "model": model,
            "messages": history,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system_prompt:
            request_body["system"] = system_prompt

        headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

        accumulated_text = ""

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self._api_base}/messages",
                json=request_body,
                headers=headers,
            ) as response:
                if response.status_code != 200:
                    error = await response.aread()
                    yield f"[Error: Anthropic API {response.status_code}]"
                    return

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break

                    try:
                        import json
                        event = json.loads(data)
                        event_type = event.get("type", "")

                        if event_type == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                text = delta.get("text", "")
                                accumulated_text += text
                                yield text
                    except (ValueError, KeyError):
                        continue

        # Store the full response in history
        if accumulated_text:
            history.append({"role": "assistant", "content": accumulated_text})
            self._conversation_history[session.session_id] = history
