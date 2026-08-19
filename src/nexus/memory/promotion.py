"""L2 to L3 promotion logic for the layered memory system.

Determines when per-agent facts (L2) have accumulated enough evidence
to be promoted to shared organizational knowledge (L3). Promotion is
based on access frequency and cross-agent validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from nexus.memory.dedup import jaccard_similarity, tokenize
from nexus.memory.layered import Fact


@dataclass
class PromotionCriteria:
    """Configuration for L2 -> L3 promotion decisions.

    Attributes:
        min_access_count: Minimum times a fact must be accessed for promotion.
        min_agents_referenced: Minimum number of agents that must hold
            the same/similar fact for cross-agent promotion.
        min_age_hours: Minimum age in hours before a fact is eligible
            for promotion (prevents premature promotion of new facts).
    """

    min_access_count: int = 3
    min_agents_referenced: int = 2
    min_age_hours: int = 24


class PromotionEngine:
    """Engine that decides whether L2 facts should be promoted to L3.

    Promotion criteria:
    1. A fact accessed >= min_access_count times qualifies (high-value signal).
    2. A fact that exists (as same or similar) in >= min_agents_referenced
       different agents' L2 stores qualifies (cross-agent validation).

    Either criterion is sufficient for promotion.
    """

    def should_promote(
        self,
        fact: Fact,
        criteria: PromotionCriteria,
        all_agent_facts: dict[UUID, list[Fact]],
    ) -> bool:
        """Determine if a single fact should be promoted from L2 to L3.

        A fact qualifies for promotion if either:
        - It has been accessed >= min_access_count times, OR
        - The same/similar fact exists in >= min_agents_referenced different
          agents' L2 stores (cross-agent validation using Jaccard similarity).

        Args:
            fact: The Fact to evaluate for promotion.
            criteria: The PromotionCriteria configuration.
            all_agent_facts: All agent L2 stores (agent_id -> list of facts).

        Returns:
            True if the fact should be promoted to L3.
        """
        # Criterion 1: high access count
        if fact.access_count >= criteria.min_access_count:
            return True

        # Criterion 2: cross-agent validation
        fact_tokens = tokenize(fact.content)
        if not fact_tokens:
            return False

        agents_with_similar = 0
        for _agent_id, agent_facts in all_agent_facts.items():
            for other_fact in agent_facts:
                other_tokens = tokenize(other_fact.content)
                if jaccard_similarity(fact_tokens, other_tokens) >= 0.8:
                    agents_with_similar += 1
                    break  # Only count each agent once

        return agents_with_similar >= criteria.min_agents_referenced

    def promote_eligible(
        self,
        all_agent_facts: dict[UUID, list[Fact]],
        criteria: PromotionCriteria,
    ) -> list[Fact]:
        """Scan all agents and return facts ready for promotion.

        Evaluates every fact across all agents' L2 stores and returns
        those that meet the promotion criteria.

        Args:
            all_agent_facts: All agent L2 stores (agent_id -> list of facts).
            criteria: The PromotionCriteria configuration.

        Returns:
            List of Facts that should be promoted to L3.
        """
        eligible: list[Fact] = []
        seen_contents: set[str] = set()

        for _agent_id, agent_facts in all_agent_facts.items():
            for fact in agent_facts:
                # Avoid promoting duplicate facts
                if fact.content in seen_contents:
                    continue
                if self.should_promote(fact, criteria, all_agent_facts):
                    eligible.append(fact)
                    seen_contents.add(fact.content)

        return eligible
