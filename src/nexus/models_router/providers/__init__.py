"""LLM Provider abstraction - defines the protocol all providers must implement."""

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol, runtime_checkable


@dataclass
class LLMMessage:
    """A single message in a conversation.

    Attributes:
        role: The message role (system, user, assistant, tool).
        content: The message content.
        metadata: Optional additional data (tool calls, etc.).
    """

    role: str
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Response from an LLM provider.

    Attributes:
        content: The generated text content.
        model: The model that generated the response.
        input_tokens: Number of input tokens consumed.
        output_tokens: Number of output tokens generated.
        finish_reason: Reason for completion (stop, length, tool_call).
        metadata: Provider-specific additional data.
    """

    content: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol defining the interface for all LLM providers.

    Every LLM provider (OpenAI, Anthropic, Google, Ollama) implements
    this interface to provide a consistent abstraction for model invocations.
    """

    async def complete(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion from the LLM.

        Args:
            messages: Conversation history.
            model: The model identifier to use.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Provider-specific parameters.

        Returns:
            An LLMResponse with the generated content and usage stats.
        """
        ...

    async def stream(
        self,
        messages: list[LLMMessage],
        model: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream a completion from the LLM token by token.

        Args:
            messages: Conversation history.
            model: The model identifier to use.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature.
            **kwargs: Provider-specific parameters.

        Yields:
            String chunks of the generated content.
        """
        ...

    def count_tokens(self, text: str, model: str) -> int:
        """Count the number of tokens in the given text.

        Args:
            text: The text to tokenize.
            model: The model to use for tokenization rules.

        Returns:
            The token count.
        """
        ...


__all__ = [
    "LLMMessage",
    "LLMResponse",
    "LLMProvider",
]
