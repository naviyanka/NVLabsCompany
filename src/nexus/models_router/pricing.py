"""Central model pricing table (USD per million tokens).

This is the ONE place per-model pricing lives. Every caller that needs a price
resolves it here by model family:

* the pre-flight budget guard (:mod:`nexus.models_router.preflight`),
* the cost tracker that records recorded spend,
* every provider adapter (Anthropic, OpenAI, Azure, Bedrock, Google), which
  used to each carry a private table of its own. Those tables disagreed with
  this one and with each other, so the same call was priced differently
  depending on which code path saw it, and a call the budget guard refused
  could still be recorded as affordable.

The one path that does NOT price from this table is LIVE Claude Code telemetry:
Claude emits a pre-computed, per-model cost_usd on every api_request log, so the
collector trusts Claude's own figure. This table covers everything else,
including the OFFLINE transcript reconciler that runs when telemetry is off.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass


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
# Claude 3 Haiku (the 2024-03 generation, also served by Bedrock) is a third of
# the price of 3.5 Haiku. Folding it into HAIKU would over-bill recorded spend
# by 3x, which is fine for a budget guard but wrong for an invoice.
HAIKU_3: ModelPrice = ModelPrice(
    input_per_m=0.25,
    output_per_m=1.25,
    cache_read_per_m=0.03,
    cache_write_per_m=0.3,
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
O1_MINI: ModelPrice = ModelPrice(
    input_per_m=3,
    output_per_m=12,
    cache_read_per_m=0,
    cache_write_per_m=0,
)
O3_MINI: ModelPrice = ModelPrice(
    input_per_m=1.1,
    output_per_m=4.4,
    cache_read_per_m=0,
    cache_write_per_m=0,
)
GPT4_TURBO: ModelPrice = ModelPrice(
    input_per_m=10,
    output_per_m=30,
    cache_read_per_m=0,
    cache_write_per_m=0,
)
# Bare gpt-4 is three times the price of gpt-4-turbo, so it needs its own row:
# folding it into GPT4_TURBO under-charges, which is the unsafe direction.
GPT4: ModelPrice = ModelPrice(
    input_per_m=30,
    output_per_m=60,
    cache_read_per_m=0,
    cache_write_per_m=0,
)
GPT35_TURBO: ModelPrice = ModelPrice(
    input_per_m=0.5,
    output_per_m=1.5,
    cache_read_per_m=0,
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
# Priced at the 2.0 rate, which is the higher of the two Flash generations
# (1.5 is $0.075/$0.30). One row covering both over-estimates 1.5 slightly, and
# that is the safe direction: the budget guard refuses a little early rather
# than admitting a call it cannot afford.
GEMINI_FLASH: ModelPrice = ModelPrice(
    input_per_m=0.1,
    output_per_m=0.4,
    cache_read_per_m=0.025,
    cache_write_per_m=0,
)

# ---------------------------------------------------------------------------
# Locally hosted (Ollama and similar): no per-token charge, but not free to run.
# Priced at zero because that is what the provider bills; the budget guard is
# about provider spend, not compute.
# ---------------------------------------------------------------------------
LOCAL: ModelPrice = ModelPrice(
    input_per_m=0,
    output_per_m=0,
    cache_read_per_m=0,
    cache_write_per_m=0,
)

# ---------------------------------------------------------------------------
# Amazon Bedrock first-party models
# ---------------------------------------------------------------------------
TITAN: ModelPrice = ModelPrice(
    input_per_m=0.2,
    output_per_m=0.6,
    cache_read_per_m=0,
    cache_write_per_m=0,
)

# ---------------------------------------------------------------------------
# Default: when the model id is unknown, assume Sonnet (the historical default)
# ---------------------------------------------------------------------------
DEFAULT_PRICE: ModelPrice = SONNET

# Pattern to strip variant suffixes like [1m] from model identifiers
_VARIANT_SUFFIX_RE = re.compile(r"\[[^\]]*\]\s*$")

# Claude 3 Haiku, distinguished from 3.5 Haiku ("claude-3-5-haiku-…"), which is
# three times the price. Matches "claude-3-haiku-…" and "claude-haiku-3" but not
# "claude-haiku-3.5".
_HAIKU_3_RE = re.compile(r"3-haiku|haiku-3(?![.-]5)")


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
        # Claude 3 Haiku, not 3.5: "claude-3-haiku-…" / "anthropic.claude-3-haiku".
        return HAIKU_3 if _HAIKU_3_RE.search(m) else HAIKU
    if "sonnet" in m:
        return SONNET
    if "titan" in m:
        return TITAN
    if "gpt-4o-mini" in m:
        return GPT4O_MINI
    if "gpt-4o" in m:
        return GPT4O
    # gpt-4.1 is a Turbo-generation price, not the original gpt-4 price.
    if "gpt-4-turbo" in m or "gpt-4.1" in m:
        return GPT4_TURBO
    if "gpt-4" in m:
        return GPT4
    # Azure's deployment id drops the dot, so both spellings have to match.
    if "gpt-3.5" in m or "gpt-35" in m:
        return GPT35_TURBO
    if "o1-mini" in m:
        return O1_MINI
    if "o3-mini" in m:
        return O3_MINI
    if "o1" in m or "o3" in m:
        return O1
    # Flash before the general Gemini row: it is an order of magnitude cheaper,
    # and "gemini-1.5-flash" contains "gemini".
    if "flash" in m:
        return GEMINI_FLASH
    if "gemini" in m:
        return GEMINI
    if any(name in m for name in ("llama", "mistral", "mixtral", "qwen", "phi", "gemma")):
        return LOCAL
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


def estimate_cost_micros(
    model: str | None, input_tokens: int, output_tokens: int
) -> int:
    """Cost in integer micro-USD (10^-6 USD) for a plain input/output split.

    The honest unit for gateway accounting (R11/WP-22d): a real
    ``$0.0000000001`` charge rounds to 0 micros here instead of being inflated
    to a whole cent by ``estimate_cost_cents``. Rounded up so a recorded micro
    cost never lands below the true cost.
    """
    usd = estimate_cost_usd(
        model, TokenSplit(input_tokens=input_tokens, output_tokens=output_tokens)
    )
    return math.ceil(usd * 1_000_000)


def estimate_cost_cents(
    model: str | None, input_tokens: int, output_tokens: int
) -> int:
    """Cost in whole cents for a plain input/output split.

    This is what the provider adapters and the cost tracker record. It rounds
    up from micro-USD so a recorded cost never lands below the true cost (which
    is how the old per-adapter tables drifted into admitting calls the guard
    had refused), but a genuinely free call (0 micros) records 0 cents rather
    than being inflated to 1 (R11): ``math.ceil(usd*100)`` used to turn any
    sub-cent gateway charge into a full cent.
    """
    micros = estimate_cost_micros(model, input_tokens, output_tokens)
    return math.ceil(micros / 10_000)
