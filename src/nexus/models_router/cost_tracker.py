"""Cost Tracker - records LLM invocations and computes costs based on pricing tables."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# Pricing per 1000 tokens in cents (USD)
# Input/Output pricing for common models
_MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI models
    "gpt-4o": {"input": 0.25, "output": 1.0},
    "gpt-4o-mini": {"input": 0.015, "output": 0.06},
    "gpt-4-turbo": {"input": 1.0, "output": 3.0},
    "gpt-3.5-turbo": {"input": 0.05, "output": 0.15},
    # Anthropic models
    "claude-sonnet-4-20250514": {"input": 0.3, "output": 1.5},
    "claude-3-5-haiku-20241022": {"input": 0.08, "output": 0.4},
    "claude-3-opus-20240229": {"input": 1.5, "output": 7.5},
    # Google models
    "gemini-1.5-pro": {"input": 0.125, "output": 0.5},
    "gemini-1.5-flash": {"input": 0.0075, "output": 0.03},
    "gemini-2.0-flash": {"input": 0.01, "output": 0.04},
    # Local models (zero cost)
    "llama3": {"input": 0.0, "output": 0.0},
    "mistral": {"input": 0.0, "output": 0.0},
    "codellama": {"input": 0.0, "output": 0.0},
}


@dataclass
class InvocationRecord:
    """Record of a single LLM invocation with cost data.

    Attributes:
        id: Unique record identifier.
        provider: The LLM provider used.
        model: The specific model invoked.
        input_tokens: Number of input tokens.
        output_tokens: Number of output tokens.
        cost_cents: Computed cost in cents.
        agent_id: The agent that triggered the invocation.
        task_id: The task being executed.
        company_id: The company scope.
        timestamp: When the invocation occurred.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_cents: int = 0
    agent_id: uuid.UUID | None = None
    task_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class CostTracker:
    """Tracks LLM invocation costs with per-model pricing.

    Records each invocation, computes costs based on the pricing table,
    and provides aggregation methods for budget monitoring.
    """

    def __init__(
        self,
        pricing: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """Initialize the cost tracker.

        Args:
            pricing: Model pricing table. Uses defaults if None.
                Keys are model names, values are dicts with 'input'
                and 'output' prices per 1000 tokens in cents.
        """
        self._pricing = pricing or _MODEL_PRICING
        self._records: list[InvocationRecord] = []

    def get_cost_for_invocation(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> int:
        """Compute the cost in cents for a given invocation.

        Args:
            provider: The LLM provider.
            model: The model name.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.

        Returns:
            Cost in cents (rounded up to nearest cent).
        """
        model_pricing = self._pricing.get(model)
        if not model_pricing:
            # Default to a conservative estimate if model is unknown
            model_pricing = {"input": 0.1, "output": 0.3}

        input_cost = (input_tokens / 1000.0) * model_pricing["input"]
        output_cost = (output_tokens / 1000.0) * model_pricing["output"]
        total = input_cost + output_cost

        # Round up to nearest cent
        import math
        return int(math.ceil(total))

    def record_invocation(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
    ) -> InvocationRecord:
        """Record an LLM invocation and compute its cost.

        Args:
            provider: The LLM provider used.
            model: The specific model invoked.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            agent_id: The agent that triggered the invocation.
            task_id: The task being executed.
            company_id: The company scope.

        Returns:
            The recorded InvocationRecord with computed cost.
        """
        cost_cents = self.get_cost_for_invocation(
            provider, model, input_tokens, output_tokens
        )

        record = InvocationRecord(
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            agent_id=agent_id,
            task_id=task_id,
            company_id=company_id,
        )
        self._records.append(record)
        return record

    def get_total_cost(
        self,
        company_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
    ) -> int:
        """Get total cost in cents, optionally filtered.

        Args:
            company_id: Filter by company. None means all.
            agent_id: Filter by agent. None means all.

        Returns:
            Total cost in cents.
        """
        total = 0
        for record in self._records:
            if company_id and record.company_id != company_id:
                continue
            if agent_id and record.agent_id != agent_id:
                continue
            total += record.cost_cents
        return total

    def get_records(
        self,
        company_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> list[InvocationRecord]:
        """Get invocation records, optionally filtered.

        Args:
            company_id: Filter by company. None means all.
            limit: Maximum number of records to return.

        Returns:
            List of InvocationRecord objects.
        """
        filtered = self._records
        if company_id:
            filtered = [r for r in filtered if r.company_id == company_id]
        return filtered[-limit:]

    def update_pricing(self, model: str, input_price: float, output_price: float) -> None:
        """Update or add pricing for a model.

        Args:
            model: The model name.
            input_price: Price per 1000 input tokens in cents.
            output_price: Price per 1000 output tokens in cents.
        """
        self._pricing[model] = {"input": input_price, "output": output_price}
