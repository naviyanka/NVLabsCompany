"""Tests for session context compaction and token estimation.

Covers: TokenCounter estimation, truncation with word boundaries,
fits_in_context checks, CompactionStrategy enum, CompactionConfig defaults,
SessionCompactor truncate/summarize/sliding_window strategies, edge cases
(empty messages, single message, all messages fitting).
"""

import pytest

from nexus.memory.token_counter import TokenCounter
from nexus.memory.compaction import (
    CompactionConfig,
    CompactionSummary,
    MessageTooLargeError,
    resolve_compaction_budget,
    CompactionStrategy,
    SessionCompactor,
)
from nexus.models_router.capabilities import DEFAULT_LIMITS, ModelCapabilityResolver


# --- Fixtures ---


@pytest.fixture
def counter() -> TokenCounter:
    """Create a TokenCounter instance."""
    return TokenCounter()


@pytest.fixture
def compactor() -> SessionCompactor:
    """Create a SessionCompactor instance."""
    return SessionCompactor()


@pytest.fixture
def sample_messages() -> list[dict]:
    """Create a list of sample messages for testing."""
    return [
        {"role": "user", "content": "Hello, how are you today?"},
        {"role": "assistant", "content": "I am doing well, thank you for asking."},
        {"role": "user", "content": "Can you help me with a coding problem?"},
        {"role": "assistant", "content": "Of course! I would be happy to help you with coding."},
        {"role": "user", "content": "I need to sort a list in Python."},
        {"role": "assistant", "content": "You can use the sorted() function or the list.sort() method."},
        {"role": "user", "content": "What about custom sorting?"},
        {"role": "assistant", "content": "Use the key parameter with a lambda or function."},
        {"role": "user", "content": "Can you show me an example?"},
        {"role": "assistant", "content": "Sure, here is an example: sorted(items, key=lambda x: x.name)"},
    ]


@pytest.fixture
def long_messages() -> list[dict]:
    """Create a list of messages that definitely exceeds a small token budget."""
    return [
        {"role": "user", "content": "A" * 400}
        for _ in range(20)
    ]


# --- TestTokenCounter ---


class TestTokenCounter:
    """Tests for the TokenCounter class."""

    def test_estimate_tokens_empty_string(self, counter: TokenCounter) -> None:
        """Empty string should return 0 tokens."""
        assert counter.estimate_tokens("") == 0

    def test_estimate_tokens_short_text(self, counter: TokenCounter) -> None:
        """Short text should return at least 1 token."""
        result = counter.estimate_tokens("Hi")
        assert result >= 1

    def test_estimate_tokens_known_length(self, counter: TokenCounter) -> None:
        """Text of known length should give predictable estimate."""
        # 20 characters / 4 chars per token = 5 tokens
        text = "a" * 20
        result = counter.estimate_tokens(text)
        assert result == 5

    def test_estimate_tokens_long_text(self, counter: TokenCounter) -> None:
        """Long text should give proportionally larger estimate."""
        short = counter.estimate_tokens("hello")
        long_text = "hello " * 100
        long_count = counter.estimate_tokens(long_text)
        assert long_count > short

    def test_fits_in_context_true(self, counter: TokenCounter) -> None:
        """Text within budget should return True."""
        # "Hello" is 5 chars -> ~2 tokens
        assert counter.fits_in_context("Hello", 10) is True

    def test_fits_in_context_false(self, counter: TokenCounter) -> None:
        """Text exceeding budget should return False."""
        # 100 chars -> ~25 tokens
        text = "x" * 100
        assert counter.fits_in_context(text, 5) is False

    def test_fits_in_context_exact_boundary(self, counter: TokenCounter) -> None:
        """Text exactly at budget boundary should fit."""
        # 8 chars -> 2 tokens
        text = "a" * 8
        assert counter.fits_in_context(text, 2) is True

    def test_truncate_to_tokens_no_truncation_needed(
        self, counter: TokenCounter
    ) -> None:
        """Text that fits should be returned unchanged."""
        text = "Hello world"
        result = counter.truncate_to_tokens(text, 100)
        assert result == text

    def test_truncate_to_tokens_truncates(self, counter: TokenCounter) -> None:
        """Long text should be truncated to fit."""
        text = "The quick brown fox jumps over the lazy dog " * 10
        result = counter.truncate_to_tokens(text, 5)
        # 5 tokens * 4 chars = 20 chars max
        assert len(result) <= 20
        assert len(result) > 0

    def test_truncate_to_tokens_word_boundary(
        self, counter: TokenCounter
    ) -> None:
        """Truncation should respect word boundaries."""
        text = "Hello wonderful beautiful world today"
        result = counter.truncate_to_tokens(text, 3)
        # Should not end mid-word
        assert not result.endswith("wond")
        # Should end at a word boundary (no trailing partial words)
        assert result == result.rstrip()

    def test_truncate_to_tokens_empty(self, counter: TokenCounter) -> None:
        """Empty text should return empty string."""
        assert counter.truncate_to_tokens("", 10) == ""

    def test_truncate_to_tokens_zero_budget(
        self, counter: TokenCounter
    ) -> None:
        """Zero token budget should return empty string."""
        assert counter.truncate_to_tokens("Hello world", 0) == ""


# --- TestCompactionConfig ---


class TestCompactionConfig:
    """Tests for the CompactionConfig dataclass."""

    def test_default_config(self) -> None:
        """Default config should have expected values."""
        config = CompactionConfig()
        assert config.strategy == CompactionStrategy.TRUNCATE
        assert config.max_tokens == 4096
        assert config.window_size == 10
        assert config.overlap_tokens == 256
        assert config.summary_ratio == 0.3

    def test_custom_config(self) -> None:
        """Custom config should use provided values."""
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_tokens=2048,
            window_size=5,
            overlap_tokens=128,
            summary_ratio=0.5,
        )
        assert config.strategy == CompactionStrategy.SUMMARIZE
        assert config.max_tokens == 2048
        assert config.window_size == 5
        assert config.overlap_tokens == 128
        assert config.summary_ratio == 0.5


# --- TestCompactionStrategy ---


class TestCompactionStrategy:
    """Tests for the CompactionStrategy enum."""

    def test_truncate_value(self) -> None:
        """TRUNCATE should have correct value."""
        assert CompactionStrategy.TRUNCATE.value == "truncate"

    def test_summarize_value(self) -> None:
        """SUMMARIZE should have correct value."""
        assert CompactionStrategy.SUMMARIZE.value == "summarize"

    def test_sliding_window_value(self) -> None:
        """SLIDING_WINDOW should have correct value."""
        assert CompactionStrategy.SLIDING_WINDOW.value == "sliding_window"


# --- TestSessionCompactor ---


class TestSessionCompactor:
    """Tests for the SessionCompactor class."""

    def test_truncate_keeps_newest(
        self, compactor: SessionCompactor, long_messages: list[dict]
    ) -> None:
        """Truncate strategy should keep newest messages that fit."""
        config = CompactionConfig(
            strategy=CompactionStrategy.TRUNCATE,
            max_tokens=200,  # Small budget
        )
        result = compactor.compact(long_messages, config)
        # Should have fewer messages than original
        assert len(result) < len(long_messages)
        # Should contain the newest messages
        assert result[-1] == long_messages[-1]

    def test_truncate_all_fit(
        self, compactor: SessionCompactor, sample_messages: list[dict]
    ) -> None:
        """When all messages fit, truncate should return them unchanged."""
        config = CompactionConfig(
            strategy=CompactionStrategy.TRUNCATE,
            max_tokens=10000,  # Large budget
        )
        result = compactor.compact(sample_messages, config)
        assert result == sample_messages

    def test_summarize_produces_summary_and_recent(
        self, compactor: SessionCompactor, long_messages: list[dict]
    ) -> None:
        """Summarize strategy should produce a summary message plus recent messages."""
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_tokens=300,
            summary_ratio=0.3,
        )
        result = compactor.compact(long_messages, config)
        # First message should be the summary
        assert result[0]["role"] == "system"
        assert "[Summary]" in result[0]["content"] or "[Summary of previous context]" in result[0]["content"]
        # Should have fewer messages than original
        assert len(result) < len(long_messages)

    def test_summarize_all_fit(
        self, compactor: SessionCompactor, sample_messages: list[dict]
    ) -> None:
        """When all messages fit, summarize should return them unchanged."""
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_tokens=10000,
            summary_ratio=0.3,
        )
        result = compactor.compact(sample_messages, config)
        assert result == sample_messages

    def test_sliding_window_correct_window(
        self, compactor: SessionCompactor, sample_messages: list[dict]
    ) -> None:
        """Sliding window should keep exactly window_size recent messages."""
        config = CompactionConfig(
            strategy=CompactionStrategy.SLIDING_WINDOW,
            max_tokens=50,  # Small to trigger compaction
            window_size=3,
            overlap_tokens=0,
        )
        result = compactor.compact(sample_messages, config)
        # With overlap_tokens=0, should just get the window
        assert len(result) == 3
        assert result[-1] == sample_messages[-1]
        assert result[-2] == sample_messages[-2]
        assert result[-3] == sample_messages[-3]

    def test_sliding_window_with_overlap(
        self, compactor: SessionCompactor, sample_messages: list[dict]
    ) -> None:
        """Sliding window with overlap should include context from older messages."""
        config = CompactionConfig(
            strategy=CompactionStrategy.SLIDING_WINDOW,
            max_tokens=50,  # Small to trigger compaction
            window_size=3,
            overlap_tokens=100,
        )
        result = compactor.compact(sample_messages, config)
        # Should have window + 1 context message
        assert len(result) == 4
        assert result[0]["role"] == "system"
        assert "[Context]" in result[0]["content"]
        # Last 3 should be the window messages
        assert result[-1] == sample_messages[-1]

    def test_sliding_window_all_fit_in_window(
        self, compactor: SessionCompactor
    ) -> None:
        """When messages count <= window_size, return all unchanged (no compaction needed since they fit)."""
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        config = CompactionConfig(
            strategy=CompactionStrategy.SLIDING_WINDOW,
            max_tokens=5,  # Force compaction
            window_size=5,
            overlap_tokens=50,
        )
        result = compactor.compact(messages, config)
        # 2 messages <= window_size of 5, so sliding_window returns all
        assert result == messages

    def test_empty_messages(self, compactor: SessionCompactor) -> None:
        """Empty message list should return empty list."""
        config = CompactionConfig(strategy=CompactionStrategy.TRUNCATE, max_tokens=100)
        result = compactor.compact([], config)
        assert result == []

    def test_single_message_fits(self, compactor: SessionCompactor) -> None:
        """Single message that fits should be returned unchanged."""
        messages = [{"role": "user", "content": "Hello"}]
        config = CompactionConfig(strategy=CompactionStrategy.TRUNCATE, max_tokens=100)
        result = compactor.compact(messages, config)
        assert result == messages

    def test_single_message_truncate(self, compactor: SessionCompactor) -> None:
        """Single message that exceeds budget: truncate keeps nothing if it does not fit."""
        messages = [{"role": "user", "content": "A" * 1000}]
        config = CompactionConfig(
            strategy=CompactionStrategy.TRUNCATE,
            max_tokens=5,
        )
        result = compactor.compact(messages, config)
        # The single message is too big, truncate will not include it
        assert result == []

    def test_get_token_count(self, compactor: SessionCompactor) -> None:
        """get_token_count should sum tokens across all messages."""
        messages = [
            {"role": "user", "content": "a" * 20},  # 5 tokens
            {"role": "assistant", "content": "b" * 20},  # 5 tokens
        ]
        count = compactor.get_token_count(messages)
        assert count == 10

    def test_get_token_count_empty(self, compactor: SessionCompactor) -> None:
        """get_token_count of empty list should be 0."""
        assert compactor.get_token_count([]) == 0

    def test_messages_without_role_key(
        self, compactor: SessionCompactor
    ) -> None:
        """Messages with only content key should still work."""
        messages = [
            {"content": "Hello world"},
            {"content": "How are you"},
        ]
        config = CompactionConfig(strategy=CompactionStrategy.TRUNCATE, max_tokens=10000)
        result = compactor.compact(messages, config)
        assert result == messages

    def test_summarize_extracts_content(
        self, compactor: SessionCompactor
    ) -> None:
        """Summarize should extract meaningful content from old messages."""
        messages = [
            {"role": "user", "content": "The weather is sunny today. It is a great day."},
            {"role": "assistant", "content": "Yes, perfect for a walk. Enjoy your day."},
            {"role": "user", "content": "I will go to the park. Thanks for the suggestion."},
            {"role": "assistant", "content": "Have fun at the park! Stay hydrated."},
            {"role": "user", "content": "What should I bring?"},
            {"role": "assistant", "content": "Bring water, sunscreen, and a hat for sun protection."},
        ]
        config = CompactionConfig(
            strategy=CompactionStrategy.SUMMARIZE,
            max_tokens=30,
            summary_ratio=0.4,
        )
        result = compactor.compact(messages, config)
        # Should have a summary as first message
        assert result[0]["role"] == "system"
        # Summary should contain extracted content
        assert len(result[0]["content"]) > 0


# --- Phase 2.2: budget-aware compaction ---


class TestModelCapabilityResolver:
    """Tests for per-model context window / max output resolution."""

    def test_registered_model_uses_registry_window(self) -> None:
        limits = ModelCapabilityResolver.resolve("gpt-4o")
        assert limits.context_window == 128000
        assert limits.max_output == 16384

    def test_family_match_for_unregistered_model(self) -> None:
        limits = ModelCapabilityResolver.resolve("claude-opus-4-6")
        assert limits.context_window == 200000
        assert limits.max_output == 32000

    def test_variant_suffix_is_stripped(self) -> None:
        assert ModelCapabilityResolver.resolve(
            "claude-sonnet-4-20250514[1m]"
        ) == ModelCapabilityResolver.resolve("claude-sonnet-4-20250514")

    def test_more_specific_family_wins(self) -> None:
        assert ModelCapabilityResolver.resolve("gpt-4o-mini").max_output == 16384

    def test_unknown_model_falls_back(self) -> None:
        assert ModelCapabilityResolver.resolve("who-knows-1") == DEFAULT_LIMITS
        assert ModelCapabilityResolver.resolve(None) == DEFAULT_LIMITS


class TestResolveCompactionBudget:
    """Tests for budget derivation from a model's context window."""

    def test_subtracts_overheads_and_applies_ratio(self) -> None:
        # gpt-4o: 128000 window, reserve 4096
        budget = resolve_compaction_budget(
            "gpt-4o",
            system_prompt_tokens=1000,
            tool_schema_tokens=2000,
            output_reserve_tokens=4096,
            threshold_ratio=0.5,
        )
        assert budget == int((128000 - 1000 - 2000 - 4096) * 0.5)

    def test_reserve_is_capped_at_model_max_output(self) -> None:
        # gpt-4-turbo max_output is 4096, so a 100k reserve clamps to 4096.
        budget = resolve_compaction_budget(
            "gpt-4-turbo",
            output_reserve_tokens=100_000,
            threshold_ratio=1.0,
        )
        assert budget == 128000 - 4096

    def test_overheads_exceeding_window_yield_zero(self) -> None:
        assert (
            resolve_compaction_budget("gpt-4o", system_prompt_tokens=500_000) == 0
        )

    def test_ratio_is_clamped(self) -> None:
        big = resolve_compaction_budget("gpt-4o", threshold_ratio=5.0)
        assert big == 128000 - 4096


class TestCompactIncremental:
    """Tests for multi-pass incremental compaction with a watermark."""

    @staticmethod
    def _thread(count: int) -> list[dict]:
        return [
            {
                "id": f"m{i}",
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"Message number {i} about topic {i % 7} with filler text.",
            }
            for i in range(count)
        ]

    def test_two_hundred_messages_compact_in_multiple_monotonic_passes(
        self, compactor: SessionCompactor
    ) -> None:
        messages = self._thread(200)
        passes = compactor.compact_incremental(messages, budget=100)

        assert len(passes) > 1
        # Watermark is monotonic in thread order.
        order = {f"m{i}": i for i in range(200)}
        marks = [order[p.watermark] for p in passes]
        assert marks == sorted(marks)
        assert len(set(marks)) == len(marks)
        # Every message is accounted for exactly once.
        assert sum(p.message_count for p in passes) == 200
        assert passes[-1].watermark == "m199"

    def test_each_pass_fits_the_budget(self, compactor: SessionCompactor) -> None:
        messages = self._thread(60)
        budget = 120
        passes = compactor.compact_incremental(messages, budget=budget)

        consumed = 0
        for p in passes:
            batch = messages[consumed : consumed + p.message_count]
            assert compactor.get_token_count(batch) <= budget
            consumed += p.message_count

    def test_resume_from_watermark_skips_covered_messages(
        self, compactor: SessionCompactor
    ) -> None:
        messages = self._thread(40)
        first = compactor.compact_incremental(messages, budget=100)[0]

        resumed = compactor.compact_incremental(
            messages, budget=100, since_watermark=first.watermark
        )
        assert sum(p.message_count for p in resumed) == 40 - first.message_count

    def test_oversized_message_raises(self, compactor: SessionCompactor) -> None:
        messages = [
            {"id": "a", "role": "user", "content": "short"},
            {"id": "b", "role": "user", "content": "x " * 5000},
        ]
        with pytest.raises(MessageTooLargeError) as exc:
            compactor.compact_incremental(messages, budget=50)
        assert exc.value.index == 1
        assert exc.value.budget == 50

    def test_non_positive_budget_raises(self, compactor: SessionCompactor) -> None:
        with pytest.raises(ValueError):
            compactor.compact_incremental(self._thread(3), budget=0)

    def test_empty_thread_yields_no_passes(
        self, compactor: SessionCompactor
    ) -> None:
        assert compactor.compact_incremental([], budget=100) == []

    def test_messages_without_ids_use_index_watermark(
        self, compactor: SessionCompactor
    ) -> None:
        messages = [{"role": "user", "content": f"item {i}"} for i in range(5)]
        passes = compactor.compact_incremental(messages, budget=1000)
        assert passes[-1].watermark == "4"


class TestCompactionSummary:
    """Tests for the structured five-field summary."""

    def test_classifies_into_five_fields(
        self, compactor: SessionCompactor
    ) -> None:
        messages = [
            {"role": "user", "content": "We need a caching layer for the API."},
            {"role": "assistant", "content": "We decided to use Redis for it."},
            {"role": "assistant", "content": "Created the cache module and wired it."},
            {"role": "user", "content": "What about invalidation?"},
            {"role": "assistant", "content": "Redis runs on port 6379 in staging."},
        ]
        s = compactor.summarize_structured(messages)

        assert s.decisions and "Redis" in s.decisions[0]
        assert s.actions
        assert s.open_items and s.open_items[0].endswith("?")
        assert s.topics
        assert s.facts

    def test_render_includes_populated_labels_only(
        self, compactor: SessionCompactor
    ) -> None:
        s = CompactionSummary(decisions=["use Redis"])
        rendered = s.render()
        assert "Decisions: use Redis" in rendered
        assert "Topics:" not in rendered

    def test_render_of_empty_summary(self) -> None:
        assert CompactionSummary().render() == "[Summary] (no salient content)"

    def test_blank_messages_are_skipped(
        self, compactor: SessionCompactor
    ) -> None:
        s = compactor.summarize_structured(
            [{"role": "user", "content": "   "}, {"role": "user", "content": ""}]
        )
        assert s == CompactionSummary()
