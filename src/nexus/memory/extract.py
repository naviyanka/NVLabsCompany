"""Rule-based fact extraction from agent output text.

Uses regex patterns to identify and extract structured facts from
free-text agent output. Extracted facts are stored in the layered
memory system's L2 (per-agent) layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from nexus.memory.layered import Fact


@dataclass
class ExtractionRule:
    """A regex-based rule for extracting facts from text.

    Attributes:
        pattern: Regex pattern with a capture group for the fact content.
        fact_type: Category of extracted fact (e.g., 'learned', 'behavioral').
        description: Human-readable description of what this rule matches.
    """

    pattern: str
    fact_type: str
    description: str


class FactExtractor:
    """Extracts structured facts from agent output text using regex rules.

    Each rule defines a pattern that, when matched, produces a Fact
    with the captured content and metadata about the extraction rule used.

    Example usage:
        extractor = FactExtractor(rules=FactExtractor.default_rules())
        facts = extractor.extract_facts(agent_output, agent_id)
    """

    def __init__(self, rules: list[ExtractionRule] | None = None) -> None:
        """Initialize the extractor with a set of extraction rules.

        Args:
            rules: List of ExtractionRule instances. If None, uses default_rules().
        """
        self._rules = rules if rules is not None else self.default_rules()

    @classmethod
    def default_rules(cls) -> list[ExtractionRule]:
        """Return the standard set of extraction rules.

        Includes rules for:
        - 'learned that ...' patterns (knowledge acquisition)
        - 'important: ...' patterns (high-priority facts)
        - 'note: ...' patterns (general observations)
        - 'always ...' / 'never ...' patterns (behavioral rules)
        - Error patterns (defensive rules)

        Returns:
            List of ExtractionRule instances covering common patterns.
        """
        return [
            ExtractionRule(
                pattern=r"(?i)learned\s+that\s+(.+?)(?:\.|$)",
                fact_type="learned",
                description="Knowledge acquisition: 'learned that ...'",
            ),
            ExtractionRule(
                pattern=r"(?i)important:\s*(.+?)(?:\.|$)",
                fact_type="important",
                description="High-priority fact: 'important: ...'",
            ),
            ExtractionRule(
                pattern=r"(?i)note:\s*(.+?)(?:\.|$)",
                fact_type="note",
                description="General observation: 'note: ...'",
            ),
            ExtractionRule(
                pattern=r"(?i)\b(always\s+.+?)(?:\.|$)",
                fact_type="behavioral",
                description="Behavioral rule: 'always ...'",
            ),
            ExtractionRule(
                pattern=r"(?i)\b(never\s+.+?)(?:\.|$)",
                fact_type="behavioral",
                description="Behavioral rule: 'never ...'",
            ),
            ExtractionRule(
                pattern=r"(?i)error[:\s]+(.+?)(?:\.|$)",
                fact_type="defensive",
                description="Error pattern for defensive rules",
            ),
        ]

    def extract_facts(self, text: str, agent_id: UUID) -> list[Fact]:
        """Extract facts from text using all configured rules.

        Applies each extraction rule to the input text and creates
        Fact instances for each match. Metadata includes the rule type
        and description for provenance tracking.

        Args:
            text: The agent output text to extract facts from.
            agent_id: The UUID of the agent that produced this text.

        Returns:
            List of extracted Fact instances (may be empty if no patterns match).
        """
        facts: list[Fact] = []
        seen_contents: set[str] = set()

        for rule in self._rules:
            matches = re.finditer(rule.pattern, text)
            for match in matches:
                content = match.group(1).strip()
                if not content or content in seen_contents:
                    continue
                seen_contents.add(content)
                facts.append(
                    Fact(
                        content=content,
                        source_agent_id=agent_id,
                        created_at=datetime.now(timezone.utc),
                        access_count=0,
                        metadata={
                            "fact_type": rule.fact_type,
                            "rule_description": rule.description,
                        },
                    )
                )

        return facts
