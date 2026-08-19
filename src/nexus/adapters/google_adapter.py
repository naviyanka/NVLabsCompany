"""Google Gemini Adapter - implements AgentAdapter Protocol for Google Gemini models.

Supports Gemini 2.0 Flash, Gemini 1.5 Pro, and Gemini 1.5 Flash models.
Uses async httpx for API communication with retry logic for rate limits.
"""

import asyncio
import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult


# Per-model pricing in cents per 1K tokens (input, output)
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.01, 0.04),
    "gemini-1.5-pro": (0.125, 0.5),
    "gemini-1.5-flash": (0.0075, 0.03),
}

# Default max retries for rate limit errors
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0

# Maximum number of messages to retain in conversation history per session
MAX_HISTORY_MESSAGES = 50


class GoogleGeminiAdapter(BaseAdapter):
    """Agent adapter for Google Gemini generative AI models.

    Implements the full AgentAdapter Protocol using async httpx to
    communicate with the Google Generative Language API. Supports function
    calling, token counting, cost tracking, and exponential backoff on rate limits.
    """

    adapter_type: str = "google_gemini"

    def __init__(self) -> None:
        """Initialize the Google Gemini adapter."""
        super().__init__()
        self._api_base = "https://generativelanguage.googleapis.com/v1beta"

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required Google Gemini configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If required keys are missing.
        """
        if "api_key" not in config:
            raise ValueError("Google Gemini adapter requires 'api_key' in config")
        if "model" not in config:
            raise ValueError("Google Gemini adapter requires 'model' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Google Gemini session with conversation history.

        Sets up the system prompt from agent config if provided.

        Args:
            session: The newly created session.
        """
        system_prompt = session.config.get("system_prompt", "")
        if system_prompt:
            session.metadata["system_prompt"] = system_prompt

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task via Google Gemini generateContent API.

        Sends the task prompt and applies retry with exponential backoff
        on rate limit (429) responses.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'temperature', 'max_tokens'.

        Returns:
            TaskResult with the model's response and usage metrics.
        """
        import httpx

        prompt = payload.get("prompt", "")
        temperature = payload.get("temperature", 0.7)
        max_tokens = payload.get("max_tokens", 4096)

        api_key = session.config["api_key"]
        model = session.config["model"]

        # Build conversation contents
        history = self._conversation_history.get(session.session_id, [])
        history.append({"role": "user", "parts": [{"text": prompt}]})

        # Build request body
        request_body: dict[str, Any] = {
            "contents": history,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        # Add system instruction if configured
        system_prompt = session.metadata.get("system_prompt", "")
        if system_prompt:
            request_body["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        }

        url = f"{self._api_base}/models/{model}:generateContent"

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
                        error=f"Google Gemini API error {response.status_code}: {error_text}",
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
        candidates = response_data.get("candidates", [])
        output_content = ""
        if candidates:
            content = candidates[0].get("content", {})
            parts = content.get("parts", [])
            if parts:
                output_content = parts[0].get("text", "")

        # Parse usage metadata
        usage_metadata = response_data.get("usageMetadata", {})
        input_tokens = usage_metadata.get("promptTokenCount", 0)
        output_tokens = usage_metadata.get("candidatesTokenCount", 0)

        # Calculate cost
        pricing = MODEL_PRICING.get(model, (0.01, 0.04))
        cost_cents = round(
            (input_tokens / 1000 * pricing[0])
            + (output_tokens / 1000 * pricing[1])
        )

        # Add assistant response to history
        history.append({
            "role": "model",
            "parts": [{"text": output_content}],
        })
        # Cap conversation history to prevent unbounded growth
        if len(history) > MAX_HISTORY_MESSAGES:
            history = history[-MAX_HISTORY_MESSAGES:]
        self._conversation_history[session.session_id] = history

        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=True,
            output=output_content,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            artifacts=[],
            logs=[f"Model: {model}, Tokens: {input_tokens}+{output_tokens}"],
        )

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Verify Google Gemini session is alive.

        Args:
            session: The active agent session.

        Returns:
            True (Gemini sessions are stateless, always alive).
        """
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        """Clean up Google Gemini session resources.

        Args:
            session: The session being terminated.
        """
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Google Gemini adapter capabilities.

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
