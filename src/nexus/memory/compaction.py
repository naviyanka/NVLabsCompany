"""Session context compaction for managing conversation history within token limits.

Provides strategies for compacting message histories when they exceed the
available context window. Supports three approaches:

- TRUNCATE: Keeps the newest messages that fit within the token budget.
- SUMMARIZE: Creates a synthetic summary of older messages and keeps recent
  messages within the remaining budget.
- SLIDING_WINDOW: Keeps the last N messages plus a context snippet from
  older messages limited to an overlap token budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from nexus.memory.token_counter import TokenCounter


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
