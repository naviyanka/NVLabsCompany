"""WP-22d / M8: micro-USD cost truth (R11).

At baseline estimate_cost_cents returned math.ceil(usd*100), so any positive
sub-cent gateway charge (OmniRoute free-tier cascade reports ~$0) inflated to
a whole cent. This over-bills at free-tier volume. Fix: round cents from
integer micro-USD, and expose estimate_cost_micros as the honest unit.

R1: tests invoke the pricing functions directly.
"""

from nexus.models_router.pricing import (
    TokenSplit,
    estimate_cost_cents,
    estimate_cost_micros,
    estimate_cost_usd,
    price_for,
)


def test_cost_micros_survives_sub_cent_charge():
    """A tiny positive charge records real micros, not an inflated 1 cent."""
    # One input token on the cheapest local price row: far below a cent.
    micros = estimate_cost_micros("llama-3", input_tokens=1, output_tokens=0)
    usd = estimate_cost_usd("llama-3", TokenSplit(input_tokens=1))

    # micros track the real cost, not rounded to a whole cent (10_000 micros)
    assert micros == __import__("math").ceil(usd * 1_000_000)
    assert micros < 10_000  # genuinely sub-cent

    # and cents no longer inflate that sub-cent charge to 1
    assert estimate_cost_cents("llama-3", input_tokens=1, output_tokens=0) == 0


def test_zero_tokens_cost_zero():
    assert estimate_cost_micros("gpt-4o", 0, 0) == 0
    assert estimate_cost_cents("gpt-4o", 0, 0) == 0


def test_cents_never_below_true_cost():
    """Cents round up from micros, so a recorded cent is never under true cost."""
    for model, i, o in [("claude-opus-4", 5000, 2000), ("gpt-4o", 1000, 500)]:
        usd = estimate_cost_usd(model, TokenSplit(input_tokens=i, output_tokens=o))
        cents = estimate_cost_cents(model, i, o)
        assert cents >= usd * 100  # never under-charges vs the true cost
        assert cents - (usd * 100) < 1  # but by less than a full cent
