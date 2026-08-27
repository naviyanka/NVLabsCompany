"""Tests for the per-model pricing module (nexus.models_router.pricing)."""

import pytest

from nexus.models_router.pricing import (
    DEFAULT_PRICE,
    GEMINI,
    GEMINI_FLASH,
    GPT4O,
    GPT4O_MINI,
    HAIKU,
    O1,
    OPUS,
    SONNET,
    ModelPrice,
    TokenSplit,
    estimate_cost_usd,
    normalize_model,
    price_for,
)


class TestModelPrice:
    """ModelPrice frozen dataclass tests."""

    def test_fields_exist(self) -> None:
        """ModelPrice has all four price fields."""
        p = ModelPrice(input_per_m=1.0, output_per_m=2.0, cache_read_per_m=0.5, cache_write_per_m=0.25)
        assert p.input_per_m == 1.0
        assert p.output_per_m == 2.0
        assert p.cache_read_per_m == 0.5
        assert p.cache_write_per_m == 0.25

    def test_frozen(self) -> None:
        """ModelPrice instances are immutable."""
        with pytest.raises(Exception):
            SONNET.input_per_m = 99  # type: ignore[misc]


class TestPriceConstants:
    """Verify all price constants have expected values."""

    def test_opus(self) -> None:
        assert OPUS == ModelPrice(15, 75, 1.5, 18.75)

    def test_sonnet(self) -> None:
        assert SONNET == ModelPrice(3, 15, 0.3, 3.75)

    def test_haiku(self) -> None:
        assert HAIKU == ModelPrice(0.8, 4, 0.08, 1.0)

    def test_gpt4o(self) -> None:
        assert GPT4O == ModelPrice(2.5, 10, 1.25, 0)

    def test_gpt4o_mini(self) -> None:
        assert GPT4O_MINI == ModelPrice(0.15, 0.6, 0.075, 0)

    def test_o1(self) -> None:
        assert O1 == ModelPrice(15, 60, 7.5, 0)

    def test_gemini(self) -> None:
        assert GEMINI == ModelPrice(1.25, 5, 0.315, 0)

    def test_default_is_sonnet(self) -> None:
        assert DEFAULT_PRICE == SONNET


class TestNormalizeModel:
    """Tests for normalize_model()."""

    def test_strips_variant_suffix(self) -> None:
        assert normalize_model("claude-opus-4-8[1m]") == "claude-opus-4-8"

    def test_strips_variant_suffix_with_content(self) -> None:
        assert normalize_model("model-name[extended]") == "model-name"

    def test_handles_none(self) -> None:
        assert normalize_model(None) == ""

    def test_handles_empty_string(self) -> None:
        assert normalize_model("") == ""

    def test_preserves_case(self) -> None:
        assert normalize_model("Claude-Opus-4[1m]") == "Claude-Opus-4"

    def test_strips_whitespace(self) -> None:
        assert normalize_model("  claude-sonnet  ") == "claude-sonnet"

    def test_no_suffix_unchanged(self) -> None:
        assert normalize_model("claude-sonnet-4") == "claude-sonnet-4"

    def test_strips_trailing_whitespace_after_bracket(self) -> None:
        assert normalize_model("model[x]  ") == "model"


class TestPriceFor:
    """Tests for price_for() keyword matching."""

    def test_opus_family(self) -> None:
        assert price_for("claude-opus-4-8") is OPUS
        assert price_for("claude-opus-4-8[1m]") is OPUS

    def test_haiku_family(self) -> None:
        assert price_for("claude-haiku-3.5") is HAIKU
        assert price_for("CLAUDE-HAIKU-3.5") is HAIKU

    def test_sonnet_family(self) -> None:
        assert price_for("claude-sonnet-4") is SONNET
        assert price_for("claude-3-5-sonnet-20241022") is SONNET

    def test_gpt4o_mini(self) -> None:
        assert price_for("gpt-4o-mini") is GPT4O_MINI
        assert price_for("GPT-4o-MINI-2024") is GPT4O_MINI

    def test_gpt4o(self) -> None:
        assert price_for("gpt-4o") is GPT4O
        assert price_for("gpt-4o-2024-05-13") is GPT4O

    def test_o1(self) -> None:
        assert price_for("o1-preview") is O1
        assert price_for("o1-mini") is O1

    def test_o3(self) -> None:
        assert price_for("o3-mini") is O1
        assert price_for("o3") is O1

    def test_gemini(self) -> None:
        assert price_for("Gemini 3.1 Pro (High)") is GEMINI

    def test_gemini_flash_is_cheaper_than_pro(self) -> None:
        """Flash is an order of magnitude cheaper, so it needs its own row."""
        assert price_for("gemini-2.0-flash") is GEMINI_FLASH
        assert price_for("gemini-1.5-flash") is GEMINI_FLASH

    def test_unknown_fallback(self) -> None:
        assert price_for("unknown-model-xyz") is DEFAULT_PRICE

    def test_none_fallback(self) -> None:
        assert price_for(None) is DEFAULT_PRICE

    def test_empty_string_fallback(self) -> None:
        assert price_for("") is DEFAULT_PRICE


class TestTokenSplit:
    """Tests for TokenSplit dataclass."""

    def test_defaults_to_zero(self) -> None:
        ts = TokenSplit()
        assert ts.input_tokens == 0
        assert ts.output_tokens == 0
        assert ts.cache_read_tokens == 0
        assert ts.cache_write_tokens == 0

    def test_custom_values(self) -> None:
        ts = TokenSplit(input_tokens=100, output_tokens=200, cache_read_tokens=50, cache_write_tokens=25)
        assert ts.input_tokens == 100
        assert ts.output_tokens == 200
        assert ts.cache_read_tokens == 50
        assert ts.cache_write_tokens == 25


class TestEstimateCostUsd:
    """Tests for estimate_cost_usd()."""

    def test_zero_tokens(self) -> None:
        cost = estimate_cost_usd("claude-sonnet-4", TokenSplit())
        assert cost == 0.0

    def test_sonnet_known_values(self) -> None:
        """1M input tokens at Sonnet rate = $3."""
        tokens = TokenSplit(input_tokens=1_000_000)
        cost = estimate_cost_usd("claude-sonnet-4", tokens)
        assert cost == pytest.approx(3.0)

    def test_sonnet_output_tokens(self) -> None:
        """1M output tokens at Sonnet rate = $15."""
        tokens = TokenSplit(output_tokens=1_000_000)
        cost = estimate_cost_usd("claude-sonnet-4", tokens)
        assert cost == pytest.approx(15.0)

    def test_opus_mixed(self) -> None:
        """Mixed token split at Opus prices."""
        tokens = TokenSplit(
            input_tokens=500_000,
            output_tokens=100_000,
            cache_read_tokens=200_000,
            cache_write_tokens=50_000,
        )
        # (500000/1M)*15 + (100000/1M)*75 + (200000/1M)*1.5 + (50000/1M)*18.75
        # = 7.5 + 7.5 + 0.3 + 0.9375 = 16.2375
        cost = estimate_cost_usd("claude-opus-4-8", tokens)
        assert cost == pytest.approx(16.2375)

    def test_none_model_uses_default(self) -> None:
        """None model uses DEFAULT_PRICE (Sonnet)."""
        tokens = TokenSplit(input_tokens=1_000_000)
        cost = estimate_cost_usd(None, tokens)
        assert cost == pytest.approx(3.0)

    def test_gpt4o_mini_cost(self) -> None:
        """GPT-4o-mini pricing verification."""
        tokens = TokenSplit(input_tokens=1_000_000, output_tokens=1_000_000)
        cost = estimate_cost_usd("gpt-4o-mini", tokens)
        # (1M/1M)*0.15 + (1M/1M)*0.6 = 0.75
        assert cost == pytest.approx(0.75)
