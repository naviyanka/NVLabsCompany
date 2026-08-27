"""Per-model context window and max-output resolution.

Compaction needs to know how much room a model actually has before it can
decide what to drop. This resolves a model id to its ``(context_window,
max_output)`` pair the same way :mod:`nexus.models_router.pricing` resolves
prices: exact registry hit first, then family keyword match, then a
conservative default.

Family matching is ordered — the most specific prefix wins (``gpt-4o-mini``
before ``gpt-4o``).
"""

from __future__ import annotations

from dataclasses import dataclass

from nexus.models_router.pricing import normalize_model
from nexus.models_router.provider_registry import ProviderRegistry


@dataclass(frozen=True)
class ModelLimits:
    """Token limits for a model.

    Attributes:
        context_window: Total tokens the model accepts (input + output).
        max_output: Maximum tokens the model will generate in one response.
    """

    context_window: int
    max_output: int


# Ordered most-specific-first; matched as substrings of the lowercased model id.
_FAMILY_LIMITS: tuple[tuple[str, ModelLimits], ...] = (
    ("opus", ModelLimits(200_000, 32_000)),
    ("sonnet", ModelLimits(200_000, 64_000)),
    ("haiku", ModelLimits(200_000, 8_192)),
    ("gpt-4o-mini", ModelLimits(128_000, 16_384)),
    ("gpt-4o", ModelLimits(128_000, 16_384)),
    ("gpt-4-turbo", ModelLimits(128_000, 4_096)),
    ("o1", ModelLimits(200_000, 100_000)),
    ("o3", ModelLimits(200_000, 100_000)),
    ("gemini-1.5-pro", ModelLimits(2_000_000, 8_192)),
    ("gemini", ModelLimits(1_000_000, 8_192)),
    ("deepseek", ModelLimits(64_000, 8_192)),
    ("mistral", ModelLimits(32_768, 8_192)),
    ("mixtral", ModelLimits(32_768, 8_192)),
    ("llama", ModelLimits(8_192, 4_096)),
)

# When the model id is unknown, assume a mid-size window and a small output cap.
DEFAULT_LIMITS: ModelLimits = ModelLimits(128_000, 4_096)


class ModelCapabilityResolver:
    """Resolves a model id to its context window and max output tokens."""

    @staticmethod
    def resolve(model: str | None) -> ModelLimits:
        """Return the token limits for ``model``.

        The registry is authoritative for the context window when the model is
        registered; ``max_output`` always comes from the family table because
        the registry does not track it.

        Args:
            model: Model identifier, optionally with a variant suffix.

        Returns:
            The resolved :class:`ModelLimits`.
        """
        m = normalize_model(model).lower()

        limits = DEFAULT_LIMITS
        for keyword, family_limits in _FAMILY_LIMITS:
            if keyword in m:
                limits = family_limits
                break

        registered = ModelCapabilityResolver._registry_context_window(m)
        if registered is not None:
            limits = ModelLimits(registered, limits.max_output)

        return limits

    @staticmethod
    def _registry_context_window(normalized_model: str) -> int | None:
        """Look up an exact model's context window in the provider registry."""
        for provider in ProviderRegistry.list_providers():
            for name, caps in provider.capabilities.items():
                if name.lower() == normalized_model:
                    return caps.context_window
        return None


__all__ = ["DEFAULT_LIMITS", "ModelCapabilityResolver", "ModelLimits"]
