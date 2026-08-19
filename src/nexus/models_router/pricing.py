"""Fallback-only model pricing table (USD per million tokens).

The LIVE telemetry path does NOT use this. Claude Code emits a pre-computed,
per-model cost_usd on every api_request log, so the collector trusts Claude's
own figure. This table exists solely for the OFFLINE transcript reconciler,
which runs when telemetry is off and must estimate cost from raw token counts.

It supersedes old hard-coded Sonnet-for-everyone constants. Prices are now
matched per model family. This is the ONE place per-model pricing lives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelPrice:
    """USD per million tokens for one model family."""

    input_per_m: float
    output_per_m: float
    cache_read_per_m: float
    cache_write_per_m: float


# ---------------------------------------------------------------------------
# Anthropic list prices (USD per million tokens)
# ---------------------------------------------------------------------------
OPUS: ModelPrice = ModelPrice(
    input_per_m=15,
    output_per_m=75,
    cache_read_per_m=1.5,
    cache_write_per_m=18.75,
)
SONNET: ModelPrice = ModelPrice(
    input_per_m=3,
    output_per_m=15,
    cache_read_per_m=0.3,
    cache_write_per_m=3.75,
)
HAIKU: ModelPrice = ModelPrice(
    input_per_m=0.8,
    output_per_m=4,
    cache_read_per_m=0.08,
    cache_write_per_m=1.0,
)

# ---------------------------------------------------------------------------
# OpenAI list prices (USD per million tokens)
# ---------------------------------------------------------------------------
GPT4O: ModelPrice = ModelPrice(
    input_per_m=2.5,
    output_per_m=10,
    cache_read_per_m=1.25,
    cache_write_per_m=0,
)
GPT4O_MINI: ModelPrice = ModelPrice(
    input_per_m=0.15,
    output_per_m=0.6,
    cache_read_per_m=0.075,
    cache_write_per_m=0,
)
O1: ModelPrice = ModelPrice(
    input_per_m=15,
    output_per_m=60,
    cache_read_per_m=7.5,
    cache_write_per_m=0,
)

# ---------------------------------------------------------------------------
# Google Gemini list prices (USD per million tokens)
# ---------------------------------------------------------------------------
GEMINI: ModelPrice = ModelPrice(
    input_per_m=1.25,
    output_per_m=5,
    cache_read_per_m=0.315,
    cache_write_per_m=0,
)

# ---------------------------------------------------------------------------
# Default: when the model id is unknown, assume Sonnet (the historical default)
# ---------------------------------------------------------------------------
DEFAULT_PRICE: ModelPrice = SONNET

# Pattern to strip variant suffixes like [1m] from model identifiers
_VARIANT_SUFFIX_RE = re.compile(r"\[[^\]]*\]\s*$")


def normalize_model(model: str | None) -> str:
    """Strip variant suffix so ``claude-opus-4-8[1m]`` resolves to ``claude-opus-4-8``.

    Case is preserved; matching is done case-insensitively in :func:`price_for`.
    """
    return _VARIANT_SUFFIX_RE.sub("", (model or "").strip())


def price_for(model: str | None) -> ModelPrice:
    """Resolve a model id to its price row by family, falling back to Sonnet.

    Keyword matching is performed case-insensitively on the normalized model name.
    """
    m = normalize_model(model).lower()
    if "opus" in m:
        return OPUS
    if "haiku" in m:
        return HAIKU
    if "sonnet" in m:
        return SONNET
    if "gpt-4o-mini" in m:
        return GPT4O_MINI
    if "gpt-4o" in m:
        return GPT4O
    if "o1" in m or "o3" in m:
        return O1
    if "gemini" in m:
        return GEMINI
    return DEFAULT_PRICE


@dataclass
class TokenSplit:
    """Token split used by the cost estimator (matches AgentUsage token fields)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


def estimate_cost_usd(model: str | None, tokens: TokenSplit) -> float:
    """Estimate USD cost for a token split using the model's fallback price row.

    Used only by the transcript reconciler; the live path trusts Claude's cost.
    """
    p = price_for(model)
    return (
        (tokens.input_tokens / 1_000_000) * p.input_per_m
        + (tokens.output_tokens / 1_000_000) * p.output_per_m
        + (tokens.cache_read_tokens / 1_000_000) * p.cache_read_per_m
        + (tokens.cache_write_tokens / 1_000_000) * p.cache_write_per_m
    )
