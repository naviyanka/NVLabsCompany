"""Model Router - multi-provider LLM abstraction with task-based selection and cost tracking."""

from nexus.models_router.router import ModelRouter, ModelConfig
from nexus.models_router.cost_tracker import CostTracker
from nexus.models_router.pricing import (
    ModelPrice,
    TokenSplit,
    normalize_model,
    price_for,
    estimate_cost_usd,
)
from nexus.models_router.providers import LLMProvider, LLMResponse
from nexus.models_router.provider_registry import (
    ProviderRegistry,
    LLMProviderSpec,
    ModelCapabilities,
)

__all__ = [
    "ModelRouter",
    "ModelConfig",
    "CostTracker",
    "ModelPrice",
    "TokenSplit",
    "normalize_model",
    "price_for",
    "estimate_cost_usd",
    "LLMProvider",
    "LLMResponse",
    "ProviderRegistry",
    "LLMProviderSpec",
    "ModelCapabilities",
]
