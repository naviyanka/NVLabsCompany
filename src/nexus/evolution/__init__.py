"""Evolution Engine - continuous improvement and self-optimization for NEXUS.

The evolution engine observes agent performance, analyzes failures,
proposes improvements, evaluates them in sandboxes, and promotes changes
ONLY with explicit approval gates. Auto-promotion is never allowed.
"""

from nexus.evolution.ab_testing import ABTestFramework
from nexus.evolution.agent_evolution import AgentEvolution
from nexus.evolution.analyzer import FailureAnalyzer
from nexus.evolution.evaluator import ProposalEvaluator
from nexus.evolution.failure_alchemy import FailureAlchemist
from nexus.evolution.isolated_sandbox import IsolatedSandbox, ResourceLimitExceeded
from nexus.evolution.llm_evolution import LLMEvolutionAdvisor
from nexus.evolution.llm_proposer import LLMImprovementProposer
from nexus.evolution.observer import EvolutionObserver
from nexus.evolution.promoter import ChangePromoter
from nexus.evolution.proposer import ImprovementProposer
from nexus.evolution.sandbox import EvolutionSandbox
from nexus.evolution.skill_evolution import SkillEvolution
from nexus.evolution.statistical import StatisticalAnalyzer

__all__ = [
    "ABTestFramework",
    "EvolutionObserver",
    "FailureAnalyzer",
    "FailureAlchemist",
    "ImprovementProposer",
    "IsolatedSandbox",
    "LLMEvolutionAdvisor",
    "LLMImprovementProposer",
    "EvolutionSandbox",
    "ProposalEvaluator",
    "ChangePromoter",
    "ResourceLimitExceeded",
    "SkillEvolution",
    "AgentEvolution",
    "StatisticalAnalyzer",
]
