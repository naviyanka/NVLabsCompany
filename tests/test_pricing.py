"""Tests for the per-model pricing module (nexus.models_router.pricing)."""

import pathlib

import pytest

from nexus.models_router.pricing import (
    DEFAULT_PRICE,
    GEMINI,
    GEMINI_FLASH,
    GPT4,
    GPT4_TURBO,
    GPT4O,
    GPT4O_MINI,
    HAIKU,
    HAIKU_3,
    O1,
    O1_MINI,
    O3_MINI,
    OPUS,
    SONNET,
    TITAN,
    ModelPrice,
    TokenSplit,
    estimate_cost_cents,
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
        assert price_for("o1") is O1

    def test_o3(self) -> None:
        assert price_for("o3") is O1

    def test_mini_reasoning_models_are_cheaper(self) -> None:
        """o1-mini and o3-mini are far cheaper than full o1, so they get own rows."""
        assert price_for("o1-mini") is O1_MINI
        assert price_for("o3-mini") is O3_MINI
        assert O1_MINI.input_per_m < O1.input_per_m
        assert O3_MINI.input_per_m < O1_MINI.input_per_m

    def test_gpt4_is_not_turbo_priced(self) -> None:
        """Bare gpt-4 costs 3x gpt-4-turbo; gpt-4.1 is a Turbo-generation price."""
        assert price_for("gpt-4") is GPT4
        assert price_for("gpt-4-turbo") is GPT4_TURBO
        assert price_for("gpt-4.1") is GPT4_TURBO
        assert GPT4.input_per_m > GPT4_TURBO.input_per_m

    def test_haiku_3_is_cheaper_than_haiku_35(self) -> None:
        """Claude 3 Haiku is a third of 3.5 Haiku's price."""
        assert price_for("claude-3-haiku-20240307") is HAIKU_3
        assert price_for("anthropic.claude-3-haiku") is HAIKU_3
        assert price_for("claude-3-5-haiku-20241022") is HAIKU
        assert price_for("claude-haiku-3.5") is HAIKU
        assert HAIKU_3.input_per_m < HAIKU.input_per_m

    def test_titan(self) -> None:
        assert price_for("amazon.titan-text-express") is TITAN

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


class TestEstimateCostCents:
    """Tests for estimate_cost_cents(), used by the adapters and cost tracker."""

    def test_rounds_up(self) -> None:
        """1000 in + 1000 out at Sonnet = 1.8 cents, recorded as 2."""
        assert estimate_cost_cents("claude-sonnet-4", 1000, 1000) == 2

    def test_zero_tokens_is_free(self) -> None:
        assert estimate_cost_cents("claude-sonnet-4", 0, 0) == 0

    def test_local_model_is_free(self) -> None:
        """Rounding up must not invent a cent for a zero-priced model."""
        assert estimate_cost_cents("llama3", 10_000, 5_000) == 0

    def test_never_under_charges_the_budget_guard(self) -> None:
        """Recorded cents must never sit below the USD figure the guard used."""
        for model in ("gpt-4o", "claude-opus-4-20250514", "gemini-1.5-flash", "o3-mini"):
            usd = estimate_cost_usd(model, TokenSplit(input_tokens=7_777, output_tokens=3_333))
            assert estimate_cost_cents(model, 7_777, 3_333) >= usd * 100


class TestAdaptersShareTheCentralTable:
    """The provider adapters must not carry pricing tables of their own."""

    def test_no_adapter_defines_its_own_table(self) -> None:
        import pkgutil

        import nexus.adapters as adapters_pkg

        root = pathlib.Path(adapters_pkg.__path__[0])
        offenders = [
            mod.name
            for mod in pkgutil.iter_modules(adapters_pkg.__path__)
            if "MODEL_PRICING" in (root / f"{mod.name}.py").read_text(encoding="utf-8")
        ]
        assert offenders == []
