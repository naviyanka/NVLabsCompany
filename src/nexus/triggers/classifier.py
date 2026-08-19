"""Inbound message classifier - determines if a message is a directive or communication.

Uses regex-based heuristics to classify text as either a communication (question)
or a directive (actionable command).
"""

import re

from nexus.triggers.types import InboundKind

# Question-word patterns that indicate a communication
_QUESTION_WORDS = re.compile(
    r"^\s*("
    r"what|how|when|where|who|why|is|are|do|does|did|can|could|status|any"
    r")\b",
    re.IGNORECASE,
)

# Imperative verbs that indicate a directive even in question-like text
_IMPERATIVE_VERBS = re.compile(
    r"\b("
    r"fix|build|ship|deploy|run|write|create|add|remove|delete|"
    r"refactor|implement|update|merge|revert"
    r")\b",
    re.IGNORECASE,
)


def classify_inbound_kind(text: str) -> InboundKind:
    """Classify inbound text as either a directive or communication.

    Classification rules:
    - Empty text is treated as communication.
    - Text starting with a question word AND ending with '?' AND containing
      no imperative verbs is classified as communication.
    - Everything else is classified as a directive.

    Args:
        text: The inbound message text to classify.

    Returns:
        InboundKind.communication for questions, InboundKind.directive for commands.
    """
    stripped = text.strip()
    if not stripped:
        return InboundKind.communication

    starts_with_question = _QUESTION_WORDS.match(stripped) is not None
    ends_with_question_mark = stripped.endswith("?")
    has_imperative = _IMPERATIVE_VERBS.search(stripped) is not None

    if starts_with_question and ends_with_question_mark and not has_imperative:
        return InboundKind.communication

    return InboundKind.directive
