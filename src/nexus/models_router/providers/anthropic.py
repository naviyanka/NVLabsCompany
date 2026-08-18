"""Anthropic LLM Provider - async implementation of the LLMProvider protocol."""

from typing import Any, AsyncIterator

from nexus.models_router.providers import LLMMessage, LLMResponse


class AnthropicProvider:
    """Anthropic API provider implementing the LLMProvider protocol.

    Uses async HTTP client to communicate with the Anthropic Messages API.
    Supports both standard completion and streaming modes.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        api_version: str = "2023-06-01",
        timeout_seconds: float = 120.0,
    ) -> None:
        """Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key.
            base_url: Base URL for the API.
            api_version: API version string.
            timeout_seconds: Request timeout in seconds.
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds

    def _build_headers(self) -> dict[str, str]:
        """Build request headers with authentication.

        Returns:
            Dictionary of HTTP headers.
        """
        return {
            "x-api-key": self._api_key,
            "anthropic-version": self._api_version,
            "Content-Type": "application/json",
        }

    def _format_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[dict[str, str]]]:
        """Convert LLMMessage objects to Anthropic API format.

        Anthropic requires system messages to be passed separately.

        Args:
            messages: List of conversation messages.

        Returns:
            Tuple of (system_prompt, message_list).
        """
        system_prompt: str | None = None
        formatted: list[dict[str, str]] = []

        for msg in messages:
            if msg.role == "system":
                system_prompt = msg.content
            else:
                formatted.append({"role": msg.role, "content": msg.content})

        return system_prompt, formatted

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using the Anthropic Messages API.

        Args:
            messages: Conversation history.
            model: Model identifier (e.g., claude-sonnet-4-20250514).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Additional parameters (top_p, top_k, etc.).

        Returns:
            An LLMResponse with generated content and token usage.

        Raises:
            RuntimeError: If the API request fails.
        """
        import httpx

        system_prompt, formatted_messages = self._format_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            payload["system"] = system_prompt
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/v1/messages",
                headers=self._build_headers(),
                json=payload,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Anthropic API error {response.status_code}: {response.text}"
                )

            data = response.json()
            content_blocks = data.get("content", [])
            content = "".join(
                block["text"] for block in content_blocks if block["type"] == "text"
            )
            usage = data.get("usage", {})

            return LLMResponse(
                content=content,
                model=data.get("model", model),
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
                finish_reason=data.get("stop_reason", "end_turn"),
                metadata={"id": data.get("id")},
            )

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a completion from Anthropic token by token.

        Args:
            messages: Conversation history.
            model: Model identifier.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Additional parameters.

        Yields:
            String chunks of the generated content.
        """
        import httpx
        import json as json_module

        system_prompt, formatted_messages = self._format_messages(messages)

        payload: dict[str, Any] = {
            "model": model,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/messages",
                headers=self._build_headers(),
                json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    event = json_module.loads(data_str)
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            yield text

    def count_tokens(self, text: str, model: str) -> int:
        """Estimate token count for the given text.

        Uses a simple character-based approximation. For production,
        use Anthropic's token counting endpoint.

        Args:
            text: The text to tokenize.
            model: The model (affects tokenizer rules).

        Returns:
            Estimated token count.
        """
        # Approximation: ~3.5 characters per token for Claude models
        return max(1, int(len(text) / 3.5))
