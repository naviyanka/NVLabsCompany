"""OpenAI LLM Provider - async implementation of the LLMProvider protocol."""

from typing import Any, AsyncIterator

from nexus.models_router.providers import LLMMessage, LLMResponse


class OpenAIProvider:
    """OpenAI API provider implementing the LLMProvider protocol.

    Uses async HTTP client to communicate with the OpenAI API.
    Supports both standard completion and streaming modes.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        organization: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key.
            base_url: Base URL for the API (allows custom endpoints).
            organization: Optional organization ID.
            timeout_seconds: Request timeout in seconds.
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._organization = organization
        self._timeout_seconds = timeout_seconds

    def _build_headers(self) -> dict[str, str]:
        """Build request headers with authentication.

        Returns:
            Dictionary of HTTP headers.
        """
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._organization:
            headers["OpenAI-Organization"] = self._organization
        return headers

    def _format_messages(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
        """Convert LLMMessage objects to OpenAI API format.

        Args:
            messages: List of conversation messages.

        Returns:
            List of dictionaries in OpenAI message format.
        """
        return [{"role": m.role, "content": m.content} for m in messages]

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using the OpenAI API.

        Args:
            messages: Conversation history.
            model: Model identifier (e.g., gpt-4o, gpt-4o-mini).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Additional parameters (top_p, frequency_penalty, etc.).

        Returns:
            An LLMResponse with generated content and token usage.

        Raises:
            RuntimeError: If the API request fails.
        """
        import httpx

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/chat/completions",
                headers=self._build_headers(),
                json=payload,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"OpenAI API error {response.status_code}: {response.text}"
                )

            data = response.json()
            choice = data["choices"][0]
            usage = data.get("usage", {})

            return LLMResponse(
                content=choice["message"]["content"],
                model=data.get("model", model),
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                finish_reason=choice.get("finish_reason", "stop"),
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
        """Stream a completion from OpenAI token by token.

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

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._build_headers(),
                json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    chunk = json_module.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content

    def count_tokens(self, text: str, model: str) -> int:
        """Estimate token count for the given text.

        Uses a simple character-based approximation (4 chars per token).
        For production use, integrate tiktoken.

        Args:
            text: The text to tokenize.
            model: The model (used for selecting the tokenizer).

        Returns:
            Estimated token count.
        """
        # Approximation: ~4 characters per token for English text
        return max(1, len(text) // 4)
