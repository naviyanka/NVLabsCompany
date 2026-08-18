"""Ollama LLM Provider - async implementation of the LLMProvider protocol for local models."""

from typing import Any, AsyncIterator

from nexus.models_router.providers import LLMMessage, LLMResponse


class OllamaProvider:
    """Ollama local model provider implementing the LLMProvider protocol.

    Communicates with a local Ollama instance for running open-source
    models without external API calls. Ideal for budget-constrained
    or privacy-sensitive workloads.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_seconds: float = 300.0,
    ) -> None:
        """Initialize the Ollama provider.

        Args:
            base_url: URL of the local Ollama server.
            timeout_seconds: Request timeout (local models may be slow).
        """
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _format_messages(self, messages: list[LLMMessage]) -> list[dict[str, str]]:
        """Convert LLMMessage objects to Ollama API format.

        Args:
            messages: List of conversation messages.

        Returns:
            List of dictionaries in Ollama message format.
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
        """Generate a completion using a local Ollama model.

        Args:
            messages: Conversation history.
            model: Model name (e.g., llama3, mistral, codellama).
            max_tokens: Maximum output tokens (num_predict in Ollama).
            temperature: Sampling temperature.
            **kwargs: Additional parameters.

        Returns:
            An LLMResponse with generated content.

        Raises:
            RuntimeError: If the Ollama server is unreachable or returns an error.
        """
        import httpx

        payload: dict[str, Any] = {
            "model": model,
            "messages": self._format_messages(messages),
            "stream": False,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._base_url}/api/chat",
                json=payload,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Ollama API error {response.status_code}: {response.text}"
                )

            data = response.json()
            message = data.get("message", {})
            content = message.get("content", "")

            # Ollama provides token counts in eval_count and prompt_eval_count
            return LLMResponse(
                content=content,
                model=data.get("model", model),
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                finish_reason="stop" if data.get("done") else "length",
            )

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a completion from Ollama token by token.

        Args:
            messages: Conversation history.
            model: Model name.
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
            "stream": True,
            "options": {
                "num_predict": max_tokens,
                "temperature": temperature,
            },
        }
        payload.update(kwargs)

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/api/chat",
                json=payload,
            ) as response:
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json_module.loads(line)
                    message = chunk.get("message", {})
                    content = message.get("content", "")
                    if content:
                        yield content
                    if chunk.get("done"):
                        break

    def count_tokens(self, text: str, model: str) -> int:
        """Estimate token count for the given text.

        Local models typically use similar tokenization to GPT models.

        Args:
            text: The text to tokenize.
            model: The model name.

        Returns:
            Estimated token count.
        """
        # Approximation: ~4 characters per token
        return max(1, len(text) // 4)
