"""Session context compaction for managing conversation history within token limits.

Provides strategies for compacting message histories when they exceed the
available context window. Supports three approaches:

- TRUNCATE: Keeps the newest messages that fit within the token budget.
- SUMMARIZE: Creates a synthetic summary of older messages and keeps recent
  messages within the remaining budget.
- SLIDING_WINDOW: Keeps the last N messages plus a context snippet from
  older messages limited to an overlap token budget.

On top of those message-list strategies this module resolves the budget from
the *model's* real context window (:func:`resolve_compaction_budget`) and
supports incremental, multi-pass compaction with a monotonic message-ID
watermark (:meth:`SessionCompactor.compact_incremental`). Oversized single
messages raise :class:`MessageTooLargeError` rather than being silently
truncated — losing part of a message without saying so corrupts the thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nexus.memory.token_counter import TokenCounter
from nexus.models_router.capabilities import ModelCapabilityResolver


class CompactionStrategy(Enum):
    """Available strategies for compacting session context.

    TRUNCATE: Keep newest messages that fit within token budget.
    SUMMARIZE: Create summary of old messages, keep recent within budget.
    SLIDING_WINDOW: Keep last N messages plus overlap context from older ones.
    """

    TRUNCATE = "truncate"
    SUMMARIZE = "summarize"
    SLIDING_WINDOW = "sliding_window"


@dataclass
class CompactionConfig:
    """Configuration for session context compaction.

    Attributes:
        strategy: The compaction strategy to use.
        max_tokens: Maximum total tokens allowed after compaction.
        window_size: Number of recent messages to keep (for sliding window).
        overlap_tokens: Token budget for context from older messages (overlap).
        summary_ratio: Compression ratio for summaries (0-1, lower = more
            compressed). Controls what fraction of the original content
            is retained in the summary.
    """

    strategy: CompactionStrategy = CompactionStrategy.TRUNCATE
    max_tokens: int = 4096
    window_size: int = 10
    overlap_tokens: int = 256
    summary_ratio: float = 0.3


# Default reserve for the model's own response when resolving a budget from
# the model's context window.
DEFAULT_OUTPUT_RESERVE_TOKENS = 4096

# Fraction of the usable window compaction is allowed to fill. Leaves headroom
# for the estimator being wrong — it is a character-ratio approximation.
DEFAULT_THRESHOLD_RATIO = 0.8


class MessageTooLargeError(Exception):
    """A single message does not fit in the compaction budget.

    Raised instead of truncating, so the caller decides how to handle content
    loss rather than discovering it downstream.
    """

    def __init__(self, index: int, message_tokens: int, budget: int) -> None:
        self.index = index
        self.message_tokens = message_tokens
        self.budget = budget
        super().__init__(
            f"Message at index {index} needs {message_tokens} tokens but the "
            f"compaction budget is {budget}; it cannot be summarized without "
            f"silent truncation."
        )


def resolve_compaction_budget(
    model: str | None,
    *,
    system_prompt_tokens: int = 0,
    tool_schema_tokens: int = 0,
    output_reserve_tokens: int = DEFAULT_OUTPUT_RESERVE_TOKENS,
    threshold_ratio: float = DEFAULT_THRESHOLD_RATIO,
) -> int:
    """Resolve the token budget available to conversation history.

    ``(context_window - system_prompt - tool_schemas - reserve) * ratio``. The
    reserve is clamped to the model's own ``max_output`` — reserving more than
    the model can ever emit only wastes history room.

    Args:
        model: Model identifier; resolved via ``ModelCapabilityResolver``.
        system_prompt_tokens: Tokens consumed by the system prompt.
        tool_schema_tokens: Tokens consumed by tool/function schemas.
        output_reserve_tokens: Tokens held back for the response.
        threshold_ratio: Fraction of the remainder to actually use (0-1].

    Returns:
        The history budget in tokens, never negative.
    """
    limits = ModelCapabilityResolver.resolve(model)
    reserve = min(max(0, output_reserve_tokens), limits.max_output)
    usable = (
        limits.context_window
        - max(0, system_prompt_tokens)
        - max(0, tool_schema_tokens)
        - reserve
    )
    if usable <= 0:
        return 0
    return int(usable * max(0.0, min(1.0, threshold_ratio)))


@dataclass
class CompactionSummary:
    """Structured five-field summary of one batch of compacted messages.

    Attributes:
        topics: What the batch was about.
        decisions: Conclusions reached.
        actions: Work performed or tools invoked.
        open_items: Unresolved questions or pending work.
        facts: Concrete details worth carrying forward.
    """

    topics: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    open_items: list[str] = field(default_factory=list)
    facts: list[str] = field(default_factory=list)

    def render(self) -> str:
        """Render the summary as a labelled block for injection as a message."""
        sections = (
            ("Topics", self.topics),
            ("Decisions", self.decisions),
            ("Actions", self.actions),
            ("Open", self.open_items),
            ("Facts", self.facts),
        )
        lines = [
            f"{label}: {'; '.join(values)}"
            for label, values in sections
            if values
        ]
        if not lines:
            return "[Summary] (no salient content)"
        return "[Summary]\n" + "\n".join(lines)


@dataclass
class CompactionPass:
    """One incremental compaction pass.

    Attributes:
        summary: The five-field summary of the messages in this pass.
        watermark: ID of the last message covered by this pass. Monotonically
            increasing across passes.
        message_count: Number of messages folded into this pass.
    """

    summary: CompactionSummary
    watermark: str
    message_count: int


class SessionCompactor:
    """Compacts session message histories to fit within token limits.

    Dispatches to the appropriate strategy based on the provided configuration.
    Messages are expected to be dictionaries with at minimum a "content" key
    containing a string value. Additional keys like "role" and "timestamp"
    are preserved but not required.
    """

    def __init__(self) -> None:
        """Initialize the SessionCompactor with a TokenCounter instance."""
        self._counter = TokenCounter()

    def compact(
        self, messages: list[dict], config: CompactionConfig
    ) -> list[dict]:
        """Compact messages according to the specified strategy.

        If messages already fit within the token budget, they are returned
        unchanged regardless of the strategy.

        Args:
            messages: List of message dicts, each with at least a "content" key.
            config: Compaction configuration specifying strategy and parameters.

        Returns:
            Compacted list of message dicts fitting within the token budget.
        """
        if not messages:
            return []

        # If messages already fit, return them unchanged
        total_tokens = self.get_token_count(messages)
        if total_tokens <= config.max_tokens:
            return list(messages)

        if config.strategy == CompactionStrategy.TRUNCATE:
            return self._truncate(messages, config.max_tokens)
        elif config.strategy == CompactionStrategy.SUMMARIZE:
            return self._summarize(
                messages, config.max_tokens, config.summary_ratio
            )
        elif config.strategy == CompactionStrategy.SLIDING_WINDOW:
            return self._sliding_window(
                messages, config.window_size, config.overlap_tokens
            )
        else:
            return list(messages)

    def compact_incremental(
        self,
        messages: list[dict],
        budget: int,
        *,
        since_watermark: str | None = None,
    ) -> list[CompactionPass]:
        """Compact a thread into successive batches, each fitting the budget.

        Greedily fills a batch until the next message would push it over
        ``budget``, emits a five-field summary for that batch, advances the
        watermark to the batch's last message ID, and repeats with the
        remainder. A thread far larger than the budget therefore yields several
        passes with a monotonically increasing watermark.

        Message IDs come from the ``"id"`` key; messages without one get their
        positional index as ID so the watermark stays well defined.

        Args:
            messages: Full ordered message list.
            budget: Token budget per batch (see :func:`resolve_compaction_budget`).
            since_watermark: Resume point. Messages up to and including this ID
                are skipped; passing an unknown ID processes nothing.

        Returns:
            One :class:`CompactionPass` per batch, in order.

        Raises:
            MessageTooLargeError: A single message exceeds ``budget``.
            ValueError: ``budget`` is not positive.
        """
        if budget <= 0:
            raise ValueError(f"budget must be positive, got {budget}")
        if not messages:
            return []

        indexed = [
            (str(msg.get("id", i)), i, msg) for i, msg in enumerate(messages)
        ]

        if since_watermark is not None:
            resume_at = len(indexed)
            for mid, i, _ in indexed:
                if mid == since_watermark:
                    resume_at = i + 1
                    break
            indexed = indexed[resume_at:]

        passes: list[CompactionPass] = []
        batch: list[tuple[str, int, dict]] = []
        batch_tokens = 0

        for mid, i, msg in indexed:
            msg_tokens = self._counter.estimate_tokens(msg.get("content", ""))
            if msg_tokens > budget:
                raise MessageTooLargeError(i, msg_tokens, budget)

            if batch and batch_tokens + msg_tokens > budget:
                passes.append(self._make_pass(batch))
                batch = []
                batch_tokens = 0

            batch.append((mid, i, msg))
            batch_tokens += msg_tokens

        if batch:
            passes.append(self._make_pass(batch))

        return passes

    def _make_pass(self, batch: list[tuple[str, int, dict]]) -> CompactionPass:
        """Build a pass from a filled batch, watermarked at its last message."""
        batch_messages = [msg for _, _, msg in batch]
        return CompactionPass(
            summary=self.summarize_structured(batch_messages),
            watermark=batch[-1][0],
            message_count=len(batch),
        )

    def summarize_structured(self, messages: list[dict]) -> CompactionSummary:
        """Build a five-field summary from messages without calling an LLM.

        Classifies each message's leading sentence by keyword into decisions,
        actions, open items, or facts, and uses user-turn openers as topics.

        Args:
            messages: Messages to summarize.

        Returns:
            The populated :class:`CompactionSummary`.
        """
        # ponytail: keyword heuristic, no LLM. Swap in an LLM summarizer here if
        # summary quality ever matters more than determinism and zero cost.
        summary = CompactionSummary()

        for msg in messages:
            content = (msg.get("content") or "").strip()
            if not content:
                continue

            excerpt = self._leading_sentence(content)
            lowered = excerpt.lower()
            role = msg.get("role", "")

            if any(
                k in lowered
                for k in ("decided", "decision", "we will", "agreed", "chose")
            ):
                summary.decisions.append(excerpt)
            elif any(
                k in lowered
                for k in ("ran ", "created", "updated", "deleted", "called", "fixed")
            ):
                summary.actions.append(excerpt)
            elif excerpt.endswith("?") or any(
                k in lowered for k in ("todo", "pending", "blocked", "unresolved")
            ):
                summary.open_items.append(excerpt)
            elif role == "user":
                summary.topics.append(excerpt)
            else:
                summary.facts.append(excerpt)

        return summary

    @staticmethod
    def _leading_sentence(content: str, max_chars: int = 160) -> str:
        """Return the first sentence of ``content``, capped at ``max_chars``."""
        cut = min(
            (pos for pos in (content.find(c) for c in ".!?") if pos != -1),
            default=-1,
        )
        if 0 <= cut < max_chars:
            return content[: cut + 1].strip()

        excerpt = content[:max_chars]
        last_space = excerpt.rfind(" ")
        if last_space > 20:
            excerpt = excerpt[:last_space]
        return excerpt.strip()

    def _truncate(self, messages: list[dict], max_tokens: int) -> list[dict]:
        """Keep the newest messages that fit within the token budget.

        Iterates from the most recent message backwards, accumulating tokens
        until the budget is exceeded. Returns messages in their original order.

        Args:
            messages: List of message dicts.
            max_tokens: Maximum token budget.

        Returns:
            List of the newest messages that fit within the budget.
        """
        if not messages:
            return []

        kept: list[dict] = []
        tokens_used = 0

        # Iterate from newest to oldest
        for msg in reversed(messages):
            content = msg.get("content", "")
            msg_tokens = self._counter.estimate_tokens(content)

            if tokens_used + msg_tokens > max_tokens:
                break

            kept.append(msg)
            tokens_used += msg_tokens

        # Reverse to restore original order
        kept.reverse()
        return kept

    def _summarize(
        self, messages: list[dict], max_tokens: int, summary_ratio: float
    ) -> list[dict]:
        """Create a summary of older messages and keep recent ones within budget.

        Splits messages into old and recent portions. Creates a synthetic
        summary message from the old messages by extracting key content.
        Keeps recent messages within the remaining token budget.

        This does NOT call an LLM - it uses a simple extractive approach,
        taking the first sentence or portion of each old message up to the
        summary token budget.

        Args:
            messages: List of message dicts.
            max_tokens: Maximum total token budget.
            summary_ratio: Fraction (0-1) controlling summary compression.

        Returns:
            List containing the summary message followed by recent messages.
        """
        if not messages:
            return []

        # Allocate token budget: summary gets summary_ratio of budget,
        # recent messages get the rest
        summary_budget = int(max_tokens * summary_ratio)
        recent_budget = max_tokens - summary_budget

        # Find how many recent messages fit in the recent budget
        recent: list[dict] = []
        recent_tokens = 0

        for msg in reversed(messages):
            content = msg.get("content", "")
            msg_tokens = self._counter.estimate_tokens(content)

            if recent_tokens + msg_tokens > recent_budget:
                break

            recent.append(msg)
            recent_tokens += msg_tokens

        recent.reverse()

        # Determine which messages are "old" (not in recent)
        num_recent = len(recent)
        old_messages = messages[: len(messages) - num_recent] if num_recent > 0 else messages

        # If no old messages, just return recent
        if not old_messages:
            return recent

        # Create extractive summary from old messages
        summary_text = self._extract_summary(old_messages, summary_budget)

        summary_message: dict = {
            "role": "system",
            "content": summary_text,
        }

        return [summary_message] + recent

    def _extract_summary(
        self, messages: list[dict], token_budget: int
    ) -> str:
        """Create an extractive summary from a list of messages.

        Takes key content from each message (first sentence or beginning
        portion) until the token budget is exhausted.

        Args:
            messages: Messages to summarize.
            token_budget: Maximum tokens for the summary.

        Returns:
            A condensed summary string.
        """
        parts: list[str] = []
        tokens_used = 0

        for msg in messages:
            content = msg.get("content", "").strip()
            if not content:
                continue

            # Extract first sentence or first ~100 chars
            # Look for sentence boundary
            sentence_end = -1
            for end_char in ".!?":
                pos = content.find(end_char)
                if pos != -1 and (sentence_end == -1 or pos < sentence_end):
                    sentence_end = pos

            if sentence_end != -1 and sentence_end < 100:
                excerpt = content[: sentence_end + 1]
            else:
                # Take first 100 chars at a word boundary
                excerpt = content[:100]
                last_space = excerpt.rfind(" ")
                if last_space > 20:
                    excerpt = excerpt[:last_space]

            excerpt_tokens = self._counter.estimate_tokens(excerpt)

            if tokens_used + excerpt_tokens > token_budget:
                # Try to fit a smaller portion
                remaining = token_budget - tokens_used
                if remaining > 0:
                    truncated = self._counter.truncate_to_tokens(
                        excerpt, remaining
                    )
                    if truncated:
                        parts.append(truncated)
                break

            parts.append(excerpt)
            tokens_used += excerpt_tokens

        if not parts:
            return "[Summary of previous context]"

        return "[Summary] " + " | ".join(parts)

    def _sliding_window(
        self,
        messages: list[dict],
        window_size: int,
        overlap_tokens: int,
    ) -> list[dict]:
        """Keep the last window_size messages plus overlap context from older ones.

        Takes the most recent window_size messages as the primary window,
        then creates a context snippet from older messages limited to the
        overlap_tokens budget.

        Args:
            messages: List of message dicts.
            window_size: Number of recent messages to keep in the window.
            overlap_tokens: Token budget for context from older messages.

        Returns:
            List containing optional overlap context message followed by
            the windowed messages.
        """
        if not messages:
            return []

        # Split into window and older messages
        if len(messages) <= window_size:
            return list(messages)

        window = messages[-window_size:]
        older = messages[:-window_size]

        # Create overlap context from older messages
        if overlap_tokens > 0 and older:
            overlap_text = self._build_overlap(older, overlap_tokens)
            if overlap_text:
                context_msg: dict = {
                    "role": "system",
                    "content": overlap_text,
                }
                return [context_msg] + window

        return window

    def _build_overlap(
        self, messages: list[dict], token_budget: int
    ) -> str:
        """Build an overlap context string from older messages.

        Takes content from the most recent older messages (closest to the
        window) until the token budget is used up.

        Args:
            messages: Older messages to extract overlap from.
            token_budget: Maximum tokens for the overlap.

        Returns:
            A context string, or empty string if no content fits.
        """
        parts: list[str] = []
        tokens_used = 0

        # Take from the end (most recent of the older messages)
        for msg in reversed(messages):
            content = msg.get("content", "").strip()
            if not content:
                continue

            msg_tokens = self._counter.estimate_tokens(content)

            if tokens_used + msg_tokens <= token_budget:
                parts.append(content)
                tokens_used += msg_tokens
            else:
                # Try to fit a truncated version
                remaining = token_budget - tokens_used
                if remaining > 0:
                    truncated = self._counter.truncate_to_tokens(
                        content, remaining
                    )
                    if truncated:
                        parts.append(truncated)
                break

        if not parts:
            return ""

        # Reverse to maintain chronological order
        parts.reverse()
        return "[Context] " + " | ".join(parts)

    def get_token_count(self, messages: list[dict]) -> int:
        """Count total tokens across all messages.

        Sums the estimated token count for the content field of each message.

        Args:
            messages: List of message dicts.

        Returns:
            Total estimated token count across all messages.
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            total += self._counter.estimate_tokens(content)
        return total
