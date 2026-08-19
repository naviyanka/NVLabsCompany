"""Simple token estimation utilities for context window management.

Provides a lightweight, heuristic-based token counter that approximates
token counts without requiring external tokenizer libraries. Uses a
character-based approach with word-boundary awareness for truncation.
"""

from __future__ import annotations

import re


class TokenCounter:
    """Estimates token counts using a simple heuristic approach.

    Uses a character-based approximation (roughly 1 token per 4 characters)
    with word-boundary awareness for clean truncation. This is intentionally
    simple and does not depend on any external tokenizer library.
    """

    CHARS_PER_TOKEN: int = 4
    """Average number of characters per token in the heuristic."""

    def estimate_tokens(self, text: str) -> int:
        """Estimate the number of tokens in a text string.

        Uses a simple heuristic: approximately 1 token per 4 characters,
        with a minimum of 1 token for any non-empty text.

        Args:
            text: The text to estimate token count for.

        Returns:
            Estimated number of tokens (0 for empty string).
        """
        if not text:
            return 0
        # Count based on characters divided by average chars per token
        # Use ceiling division to avoid underestimating
        return max(1, (len(text) + self.CHARS_PER_TOKEN - 1) // self.CHARS_PER_TOKEN)

    def fits_in_context(self, text: str, max_tokens: int) -> bool:
        """Check if a text fits within a given token budget.

        Args:
            text: The text to check.
            max_tokens: Maximum number of tokens allowed.

        Returns:
            True if the estimated token count is within the budget.
        """
        return self.estimate_tokens(text) <= max_tokens

    def truncate_to_tokens(self, text: str, max_tokens: int) -> str:
        """Truncate text to fit within a token limit, respecting word boundaries.

        Truncates at the last word boundary that fits within the token budget.
        If the text already fits, it is returned unchanged.

        Args:
            text: The text to truncate.
            max_tokens: Maximum number of tokens for the result.

        Returns:
            The truncated text (may be shorter than the budget allows due
            to word-boundary alignment).
        """
        if not text or max_tokens <= 0:
            return ""

        if self.fits_in_context(text, max_tokens):
            return text

        # Calculate approximate character budget
        char_budget = max_tokens * self.CHARS_PER_TOKEN

        # Truncate to char budget
        truncated = text[:char_budget]

        # Find the last word boundary (whitespace) to avoid cutting mid-word
        last_space = truncated.rfind(" ")
        if last_space > 0:
            truncated = truncated[:last_space]

        return truncated.rstrip()
