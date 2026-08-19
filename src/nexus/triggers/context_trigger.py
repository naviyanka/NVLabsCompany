"""Context trigger configuration - rules for context compaction and clearing.

Defines configuration dataclasses for automatic context management triggers
that fire based on time intervals and context usage percentages.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextRule:
    """A single context management rule.

    Attributes:
        enabled: Whether this rule is active.
        every_seconds: Interval in seconds between trigger evaluations.
        min_context_pct: Minimum context usage percentage to activate (standard window).
        min_context_pct_large_window: Minimum context usage percentage (large window).
        message: Instruction message when the rule fires.
    """

    enabled: bool
    every_seconds: int
    min_context_pct: int
    min_context_pct_large_window: int
    message: str


@dataclass(frozen=True)
class ContextTriggerConfig:
    """Configuration for context management triggers.

    Attributes:
        compact: Rule for context compaction (summarize and trim).
        clear: Rule for full context clearing.
    """

    compact: ContextRule
    clear: ContextRule


DEFAULT_CONTEXT_TRIGGER: ContextTriggerConfig = ContextTriggerConfig(
    compact=ContextRule(
        enabled=True,
        every_seconds=7200,
        min_context_pct=60,
        min_context_pct_large_window=40,
        message=(
            "Keep the current task, recent decisions, open questions, "
            "and file paths in play. Drop resolved tangents."
        ),
    ),
    clear=ContextRule(
        enabled=False,
        every_seconds=7200,
        min_context_pct=90,
        min_context_pct_large_window=80,
        message="",
    ),
)
