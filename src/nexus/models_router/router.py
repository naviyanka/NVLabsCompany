"""Model Router - selects the optimal LLM provider and model for a given task."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModelConfig:
    """Configuration for a specific LLM invocation.

    Attributes:
        provider: The LLM provider identifier (openai, anthropic, google, ollama).
        model_name: The specific model to use.
        max_tokens: Maximum output tokens.
        temperature: Sampling temperature (0.0 to 2.0).
        extra_params: Provider-specific additional parameters.
    """

    provider: str
    model_name: str
    max_tokens: int = 4096
    temperature: float = 0.7
    extra_params: dict[str, Any] = field(default_factory=dict)


# Default model mappings per task type and complexity
_DEFAULT_MODEL_MAP: dict[str, dict[str, ModelConfig]] = {
    "coding": {
        "high": ModelConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            max_tokens=8192,
            temperature=0.3,
        ),
        "medium": ModelConfig(
            provider="openai",
            model_name="gpt-4o",
            max_tokens=4096,
            temperature=0.5,
        ),
        "low": ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=2048,
            temperature=0.3,
        ),
    },
    "analysis": {
        "high": ModelConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            max_tokens=8192,
            temperature=0.2,
        ),
        "medium": ModelConfig(
            provider="openai",
            model_name="gpt-4o",
            max_tokens=4096,
            temperature=0.3,
        ),
        "low": ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=2048,
            temperature=0.2,
        ),
    },
    "creative": {
        "high": ModelConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            max_tokens=8192,
            temperature=0.9,
        ),
        "medium": ModelConfig(
            provider="openai",
            model_name="gpt-4o",
            max_tokens=4096,
            temperature=0.8,
        ),
        "low": ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=2048,
            temperature=0.7,
        ),
    },
    "conversation": {
        "high": ModelConfig(
            provider="openai",
            model_name="gpt-4o",
            max_tokens=4096,
            temperature=0.7,
        ),
        "medium": ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=2048,
            temperature=0.7,
        ),
        "low": ModelConfig(
            provider="ollama",
            model_name="llama3",
            max_tokens=2048,
            temperature=0.7,
        ),
    },
    "summarization": {
        "high": ModelConfig(
            provider="anthropic",
            model_name="claude-sonnet-4-20250514",
            max_tokens=4096,
            temperature=0.2,
        ),
        "medium": ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=2048,
            temperature=0.3,
        ),
        "low": ModelConfig(
            provider="ollama",
            model_name="llama3",
            max_tokens=1024,
            temperature=0.2,
        ),
    },
}


class ModelRouter:
    """Selects the optimal LLM model based on task type, complexity, and budget.

    The router considers the nature of the task (coding, analysis, creative, etc.),
    the complexity level, and the remaining budget to select an appropriate model.
    Budget-constrained situations fall back to cheaper models.
    """

    def __init__(
        self,
        model_map: dict[str, dict[str, ModelConfig]] | None = None,
        fallback_model: ModelConfig | None = None,
    ) -> None:
        """Initialize the model router.

        Args:
            model_map: Task-type to complexity-to-model mapping. Uses defaults if None.
            fallback_model: Model to use when no mapping matches.
        """
        self._model_map = model_map or _DEFAULT_MODEL_MAP
        self._fallback_model = fallback_model or ModelConfig(
            provider="openai",
            model_name="gpt-4o-mini",
            max_tokens=2048,
            temperature=0.5,
        )

    def select_model(
        self,
        task_type: str,
        complexity: str = "medium",
        budget_remaining_cents: int | None = None,
    ) -> ModelConfig:
        """Select the best model for a given task type and complexity.

        If the budget is constrained, the router may downgrade to a
        cheaper model to stay within limits.

        Args:
            task_type: The type of task (coding, analysis, creative, etc.).
            complexity: The complexity level (high, medium, low).
            budget_remaining_cents: Remaining budget. None means unlimited.

        Returns:
            A ModelConfig for the selected model.
        """
        # Look up the model for this task type and complexity
        task_models = self._model_map.get(task_type)
        if not task_models:
            return self._fallback_model

        model = task_models.get(complexity)
        if not model:
            model = task_models.get("medium", self._fallback_model)

        # If budget is tight, try to downgrade
        if budget_remaining_cents is not None and budget_remaining_cents < 50:
            # Very tight budget - use cheapest available
            low_model = task_models.get("low")
            if low_model:
                return low_model
            return self._fallback_model

        return model

    def list_task_types(self) -> list[str]:
        """List all configured task types.

        Returns:
            List of task type identifiers.
        """
        return list(self._model_map.keys())

    def get_model_for_provider(
        self, provider: str, task_type: str = "conversation"
    ) -> ModelConfig | None:
        """Find a model configuration for a specific provider.

        Args:
            provider: The provider to search for.
            task_type: Preferred task type for selection.

        Returns:
            A ModelConfig for the provider, or None if not configured.
        """
        task_models = self._model_map.get(task_type, {})
        for config in task_models.values():
            if config.provider == provider:
                return config

        # Search all task types
        for models in self._model_map.values():
            for config in models.values():
                if config.provider == provider:
                    return config
        return None
