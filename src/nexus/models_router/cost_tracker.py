"""Cost Tracker - records LLM invocations and computes costs.

Prices come from :mod:`nexus.models_router.pricing`, the one table shared with
the pre-flight budget guard and the provider adapters. This module used to carry
its own copy, which disagreed with that one.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from nexus.models_router.pricing import estimate_cost_cents


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
        default_factory=lambda: datetime.now(UTC)
    )


class CostTracker:
    """Tracks LLM invocation costs with per-model pricing.

    Records each invocation, computes costs from the central pricing table
    (:mod:`nexus.models_router.pricing`), and provides aggregation methods for
    budget monitoring. Per-model overrides can be supplied at construction or
    via :meth:`update_pricing`.
    """

    def __init__(
        self,
        pricing: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """Initialize the cost tracker.

        Args:
            pricing: Per-model price overrides. Keys are exact model names,
                values are dicts with 'input' and 'output' prices per 1000
                tokens in cents. Any model not listed here is priced from
                :mod:`nexus.models_router.pricing`.
        """
        self._pricing: dict[str, dict[str, float]] = dict(pricing or {})
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
        override = self._pricing.get(model)
        if override:
            input_cost = (input_tokens / 1000.0) * override["input"]
            output_cost = (output_tokens / 1000.0) * override["output"]
            return math.ceil(input_cost + output_cost)

        # No override for this model: price it from pricing.py, the one table the
        # pre-flight budget guard and every provider adapter also use. A second
        # built-in table here is how the two ended up disagreeing — the old one
        # charged $1/M for input where pricing.py charges $3/M, so a call the
        # guard refused could still be recorded as affordable.
        return estimate_cost_cents(model, input_tokens, output_tokens)

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
        """Override the price for one model, shadowing the central table.

        Args:
            model: The exact model name to override.
            input_price: Price per 1000 input tokens in cents.
            output_price: Price per 1000 output tokens in cents.
        """
        self._pricing[model] = {"input": input_price, "output": output_price}
