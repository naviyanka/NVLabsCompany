"""Google (Gemini) LLM Provider - async implementation of the LLMProvider protocol."""

from typing import Any, AsyncIterator

from nexus.models_router.providers import LLMMessage, LLMResponse


class GoogleProvider:
    """Google Gemini API provider implementing the LLMProvider protocol.

    Uses async HTTP client to communicate with the Gemini API.
    Supports both standard completion and streaming modes.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        timeout_seconds: float = 60.0,
    ) -> None:
        """Initialize the Google Gemini provider.

        Args:
            api_key: Google API key.
            base_url: Base URL for the Gemini API.
            timeout_seconds: Request timeout in seconds.
        """
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _format_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert LLMMessage objects to Gemini API format.

        Args:
            messages: List of conversation messages.

        Returns:
            Tuple of (system_instruction, contents).
        """
        system_instruction: str | None = None
        contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = msg.content
            else:
                role = "user" if msg.role == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg.content}],
                })

        return system_instruction, contents

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion using the Google Gemini API.

        Args:
            messages: Conversation history.
            model: Model identifier (e.g., gemini-1.5-pro, gemini-1.5-flash).
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Additional parameters.

        Returns:
            An LLMResponse with generated content and token usage.

        Raises:
            RuntimeError: If the API request fails.
        """
        import httpx

        system_instruction, contents = self._format_messages(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        payload.update(kwargs)

        url = (
            f"{self._base_url}/models/{model}:generateContent"
            f"?key={self._api_key}"
        )

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Google API error {response.status_code}: {response.text}"
                )

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                return LLMResponse(
                    content="",
                    model=model,
                    finish_reason="error",
                )

            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])
            content = "".join(p.get("text", "") for p in parts)

            usage_metadata = data.get("usageMetadata", {})

            return LLMResponse(
                content=content,
                model=model,
                input_tokens=usage_metadata.get("promptTokenCount", 0),
                output_tokens=usage_metadata.get("candidatesTokenCount", 0),
                finish_reason=candidate.get("finishReason", "STOP").lower(),
            )

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a completion from Google Gemini.

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

        system_instruction, contents = self._format_messages(messages)

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
                "temperature": temperature,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        url = (
            f"{self._base_url}/models/{model}:streamGenerateContent"
            f"?key={self._api_key}&alt=sse"
        )

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            async with client.stream(
                "POST",
                url,
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    chunk = json_module.loads(data_str)
                    candidates = chunk.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        for part in parts:
                            text = part.get("text", "")
                            if text:
                                yield text

    def count_tokens(self, text: str, model: str) -> int:
        """Estimate token count for the given text.

        Args:
            text: The text to tokenize.
            model: The model (Gemini models).

        Returns:
            Estimated token count.
        """
        # Approximation: ~4 characters per token
        return max(1, len(text) // 4)
