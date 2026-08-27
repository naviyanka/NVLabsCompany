"""Pre-flight budget estimation — refuse a call *before* it is dispatched.

Reactive accounting (charge after the response arrives) always overshoots by at
least one call. This module makes the check proactive: estimate the minimum cost
of the upcoming call from the prompt size plus an output-token reservation, and
refuse dispatch when ``spent + estimate >= limit``.

The estimate uses the fallback price table in :mod:`nexus.models_router.pricing`
because no real token counts exist before the call. It is deliberately a
*minimum*: message content only, no tool-schema tokens, so a tool-heavy request
may still cost more. Post-call accounting remains the backstop.

Note: :class:`nexus.runtime.executor.BudgetExceededError` is a separate,
agent-scoped error measured in cents. This one is USD and call-scoped.
"""

from __future__ import annotations

import logging
from typing import Callable, Literal

from nexus.models_router.pricing import TokenSplit, estimate_cost_usd

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT_RESERVATION_TOKENS = 1024
"""Assumed output size when the caller sets no ``max_output``.

Without a reservation a tiny prompt with a large provider-default response
trivially passes the guard and then blows through the cap.
"""

OnBudgetExceeded = Literal["stop", "warn"] | Callable[[float, float], None]


class BudgetExceededError(Exception):
    """Raised pre-dispatch when the next call would reach or exceed the limit."""

    def __init__(
        self, model: str | None, estimate_usd: float, spent_usd: float, limit_usd: float
    ) -> None:
        self.model = model
        self.estimate_usd = estimate_usd
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd
        super().__init__(
            f"Budget exceeded before dispatch of {model or 'unknown model'}: "
            f"spent=${spent_usd:.6f} + estimate=${estimate_usd:.6f} "
            f">= limit=${limit_usd:.6f}"
        )


def estimate_min_call_cost(
    model: str | None,
    prompt_tokens: int,
    max_output: int | None = None,
) -> float:
    """Estimate the minimum USD cost of one upcoming LLM call.

    Args:
        model: Model identifier. Resolved to a price row by family.
        prompt_tokens: Known input token count for the call.
        max_output: Output-token reservation. Falls back to
            ``DEFAULT_OUTPUT_RESERVATION_TOKENS`` when None, or to 0 when the
            prompt is empty (nothing will be dispatched).

    Returns:
        Estimated minimum cost in USD.
    """
    prompt_tokens = max(0, prompt_tokens)
    if max_output is not None:
        output_tokens = max(0, max_output)
    elif prompt_tokens > 0:
        output_tokens = DEFAULT_OUTPUT_RESERVATION_TOKENS
    else:
        output_tokens = 0
    return estimate_cost_usd(
        model, TokenSplit(input_tokens=prompt_tokens, output_tokens=output_tokens)
    )


def check_budget_preflight(
    model: str | None,
    prompt_tokens: int,
    spent_usd: float,
    limit_usd: float | None,
    max_output: int | None = None,
    on_budget_exceeded: OnBudgetExceeded = "stop",
) -> float:
    """Refuse dispatch when the estimated call cost would reach the limit.

    Args:
        model: Model identifier for pricing.
        prompt_tokens: Known input token count.
        spent_usd: Already-spent USD for the scope being capped.
        limit_usd: The cap in USD. None or <= 0 means unlimited.
        max_output: Output-token reservation, see :func:`estimate_min_call_cost`.
        on_budget_exceeded: ``"stop"`` raises, ``"warn"`` logs and allows, and a
            callable is invoked with ``(projected_usd, limit_usd)`` then allows.

    Returns:
        The estimated minimum cost in USD, whether or not the cap was hit.

    Raises:
        BudgetExceededError: When the cap is hit and the policy is ``"stop"``.
    """
    estimate = estimate_min_call_cost(model, prompt_tokens, max_output)
    if limit_usd is None or limit_usd <= 0:
        return estimate

    projected = spent_usd + estimate
    if projected < limit_usd:
        return estimate

    if callable(on_budget_exceeded):
        on_budget_exceeded(projected, limit_usd)
    elif on_budget_exceeded == "warn":
        logger.warning(
            "Budget cap reached before dispatch of %s: projected=$%.6f limit=$%.6f "
            "(allowing call per on_budget_exceeded='warn')",
            model or "unknown model",
            projected,
            limit_usd,
        )
    else:
        raise BudgetExceededError(model, estimate, spent_usd, limit_usd)
    return estimate


__all__ = [
    "DEFAULT_OUTPUT_RESERVATION_TOKENS",
    "BudgetExceededError",
    "OnBudgetExceeded",
    "estimate_min_call_cost",
    "check_budget_preflight",
]
