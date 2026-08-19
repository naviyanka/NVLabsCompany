"""LLM Evolution Advisor - LLM-driven agent and skill evolution guidance.

Provides intelligent evolution suggestions using an LLM callable with
graceful fallback to existing heuristic-based AgentEvolution and
SkillEvolution classes on any failure.
"""

import json
import uuid
from typing import Any, Awaitable, Callable

from nexus.evolution.ab_testing import ABTestFramework
from nexus.evolution.agent_evolution import AgentEvolution
from nexus.evolution.skill_evolution import SkillEvolution


AGENT_IMPROVEMENT_PROMPT = """You are an AI evolution advisor. Analyze the following agent performance data and suggest improvements.

Agent ID: {agent_id}
Performance Data: {performance_data}

Output a JSON object with the following fields:
- "model_changes": a dict mapping task_type to recommended model name
- "tool_additions": a list of tool names to add
- "tool_removals": a list of tool names to remove
- "budget_recommendation": one of "increase", "decrease", "maintain"
- "budget_amount_cents": integer adjustment in cents (0 if maintain)
- "rationale": a string explaining the reasoning behind these suggestions
- "confidence": a float between 0.0 and 1.0

Output ONLY the JSON object, no additional text.
"""

SKILL_IMPROVEMENT_PROMPT = """You are an AI evolution advisor. Analyze the following skill performance data and suggest improvements.

Skill ID: {skill_id}
Performance Data: {performance_data}

Output a JSON object with the following fields:
- "prompt_rewrites": a list of dicts, each with "original_pattern" and "suggested_replacement"
- "parameter_changes": a dict mapping parameter names to suggested values
- "optimization_notes": a list of strings with specific improvement recommendations
- "rationale": a string explaining the reasoning
- "confidence": a float between 0.0 and 1.0

Output ONLY the JSON object, no additional text.
"""

HYPOTHESIS_PROMPT = """You are an AI evolution advisor. Based on the following context, generate a testable hypothesis about what change would improve performance.

Context: {context}

Output a JSON object with the following fields:
- "hypothesis": a string describing the testable hypothesis
- "metric": the metric to measure (e.g., "accuracy", "latency_ms", "success_rate")
- "baseline_mean": estimated baseline mean for the metric (float)
- "baseline_std": estimated baseline standard deviation (float)
- "expected_effect": expected improvement magnitude (float, absolute)
- "rationale": a string explaining why this hypothesis is worth testing

Output ONLY the JSON object, no additional text.
"""


class LLMEvolutionAdvisor:
    """LLM-driven evolution advisor with heuristic fallback.

    Uses a configurable LLM callable to generate structured suggestions
    for agent and skill improvements. Integrates with ABTestFramework
    for hypothesis validation. Falls back to AgentEvolution and
    SkillEvolution heuristics on any LLM failure.

    Attributes:
        llm_callable: Async function that takes a prompt string and returns a response string.
        ab_framework: Optional ABTestFramework for hypothesis validation.
        fallback_agent_evolution: Optional AgentEvolution for heuristic fallback.
        fallback_skill_evolution: Optional SkillEvolution for heuristic fallback.
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]] | None = None,
        ab_framework: ABTestFramework | None = None,
        fallback_agent_evolution: AgentEvolution | None = None,
        fallback_skill_evolution: SkillEvolution | None = None,
    ) -> None:
        """Initialize the LLM evolution advisor.

        Args:
            llm_callable: Async function that accepts a prompt string and returns
                a response string. If None, all methods fall back to heuristics.
            ab_framework: Optional ABTestFramework for hypothesis validation.
                If None, a new instance is created internally.
            fallback_agent_evolution: Optional AgentEvolution for heuristic fallback.
                If None, a new instance is created.
            fallback_skill_evolution: Optional SkillEvolution for heuristic fallback.
                If None, a new instance is created.
        """
        self._llm_callable = llm_callable
        self._ab_framework = ab_framework or ABTestFramework()
        self._fallback_agent_evolution = fallback_agent_evolution or AgentEvolution()
        self._fallback_skill_evolution = fallback_skill_evolution or SkillEvolution()

    async def suggest_agent_improvements(
        self,
        agent_id: uuid.UUID,
        performance_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Suggest improvements for an agent based on performance data.

        Prompts the LLM with agent performance context and returns structured
        improvement suggestions. Falls back to AgentEvolution heuristics
        (optimize_model_selection, optimize_tools, optimize_budget) on any failure.

        Args:
            agent_id: The UUID of the agent to improve.
            performance_data: Dict containing performance metrics. Expected keys:
                - task_type_performance: dict mapping task_type to {model: score}
                - tool_usage_stats: dict with tool usage statistics
                - cost_history: list of recent costs in cents
                - quality_history: list of recent quality scores (0-1)

        Returns:
            Dict with keys: model_changes, tool_additions, tool_removals,
            budget_recommendation, budget_amount_cents, rationale, confidence,
            source (either "llm" or "heuristic").
        """
        if self._llm_callable is not None:
            try:
                prompt = AGENT_IMPROVEMENT_PROMPT.format(
                    agent_id=str(agent_id),
                    performance_data=json.dumps(performance_data, default=str),
                )
                response = await self._llm_callable(prompt)
                result = self._parse_agent_response(response)
                result["source"] = "llm"
                return result
            except Exception:
                pass

        # Fallback to heuristic logic
        return self._agent_heuristic_fallback(performance_data)

    async def suggest_skill_improvements(
        self,
        skill_id: uuid.UUID,
        performance_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Suggest improvements for a skill based on performance data.

        Prompts the LLM with skill metrics and returns improvement suggestions
        (prompt rewrites, parameter changes). Falls back to heuristic analysis
        on any failure.

        Args:
            skill_id: The UUID of the skill to improve.
            performance_data: Dict containing skill performance metrics. Expected keys:
                - task_results: list of dicts with 'score' field
                - version_a: optional version dict for comparison
                - version_b: optional version dict for comparison

        Returns:
            Dict with keys: prompt_rewrites, parameter_changes,
            optimization_notes, rationale, confidence, source.
        """
        if self._llm_callable is not None:
            try:
                prompt = SKILL_IMPROVEMENT_PROMPT.format(
                    skill_id=str(skill_id),
                    performance_data=json.dumps(performance_data, default=str),
                )
                response = await self._llm_callable(prompt)
                result = self._parse_skill_response(response)
                result["source"] = "llm"
                return result
            except Exception:
                pass

        # Fallback to heuristic logic
        return self._skill_heuristic_fallback(skill_id, performance_data)

    async def generate_evolution_hypothesis(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a testable hypothesis about what change would improve performance.

        The generated hypothesis is suitable for feeding into
        ABTestFramework.design_test to determine required sample size.

        Args:
            context: Dict containing relevant context for hypothesis generation.
                May include performance_data, failure_analysis, agent_id, skill_id.

        Returns:
            Dict with keys: hypothesis, metric, baseline_mean, baseline_std,
            expected_effect, rationale, source.
        """
        if self._llm_callable is not None:
            try:
                prompt = HYPOTHESIS_PROMPT.format(
                    context=json.dumps(context, default=str),
                )
                response = await self._llm_callable(prompt)
                result = self._parse_hypothesis_response(response)
                result["source"] = "llm"
                return result
            except Exception:
                pass

        # Fallback to heuristic hypothesis generation
        return self._hypothesis_heuristic_fallback(context)

    async def validate_hypothesis(
        self,
        hypothesis: dict[str, Any],
        control_results: list[float],
        treatment_results: list[float],
    ) -> dict[str, Any]:
        """Validate a hypothesis using ABTestFramework.run_test.

        Uses the ABTestFramework to run a statistical test on control vs
        treatment results and returns a structured verdict.

        Args:
            hypothesis: Dict describing the hypothesis being tested.
                Expected keys: hypothesis, metric.
            control_results: Observations from the control group.
            treatment_results: Observations from the treatment group.

        Returns:
            Dict with keys: hypothesis, metric, verdict, p_value,
            effect_size, confidence_interval, control_mean, treatment_mean,
            mean_difference, is_significant.
        """
        test_result = self._ab_framework.run_test(
            control_results=control_results,
            treatment_results=treatment_results,
        )

        return {
            "hypothesis": hypothesis.get("hypothesis", ""),
            "metric": hypothesis.get("metric", ""),
            "verdict": test_result["verdict"],
            "p_value": test_result["p_value"],
            "effect_size": test_result["effect_size"],
            "confidence_interval": test_result["confidence_interval"],
            "control_mean": test_result["control_mean"],
            "treatment_mean": test_result["treatment_mean"],
            "mean_difference": test_result["mean_difference"],
            "is_significant": test_result["verdict"] != "inconclusive",
        }

    def _parse_agent_response(self, response: str) -> dict[str, Any]:
        """Parse the LLM response for agent improvement suggestions.

        Args:
            response: Raw LLM response string (expected JSON).

        Returns:
            Validated agent improvement suggestion dict.

        Raises:
            ValueError: If response is invalid or missing required fields.
            json.JSONDecodeError: If response is not valid JSON.
        """
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")

        required_fields = [
            "model_changes",
            "tool_additions",
            "tool_removals",
            "budget_recommendation",
            "budget_amount_cents",
            "rationale",
            "confidence",
        ]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        if not isinstance(data["model_changes"], dict):
            raise ValueError("model_changes must be a dict")
        if not isinstance(data["tool_additions"], list):
            raise ValueError("tool_additions must be a list")
        if not isinstance(data["tool_removals"], list):
            raise ValueError("tool_removals must be a list")
        if data["budget_recommendation"] not in ("increase", "decrease", "maintain"):
            raise ValueError("budget_recommendation must be increase, decrease, or maintain")
        if not isinstance(data["confidence"], (int, float)):
            raise ValueError("confidence must be a number")

        return {
            "model_changes": data["model_changes"],
            "tool_additions": list(data["tool_additions"]),
            "tool_removals": list(data["tool_removals"]),
            "budget_recommendation": data["budget_recommendation"],
            "budget_amount_cents": int(data["budget_amount_cents"]),
            "rationale": str(data["rationale"]),
            "confidence": float(data["confidence"]),
        }

    def _parse_skill_response(self, response: str) -> dict[str, Any]:
        """Parse the LLM response for skill improvement suggestions.

        Args:
            response: Raw LLM response string (expected JSON).

        Returns:
            Validated skill improvement suggestion dict.

        Raises:
            ValueError: If response is invalid or missing required fields.
            json.JSONDecodeError: If response is not valid JSON.
        """
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")

        required_fields = [
            "prompt_rewrites",
            "parameter_changes",
            "optimization_notes",
            "rationale",
            "confidence",
        ]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        if not isinstance(data["prompt_rewrites"], list):
            raise ValueError("prompt_rewrites must be a list")
        if not isinstance(data["parameter_changes"], dict):
            raise ValueError("parameter_changes must be a dict")
        if not isinstance(data["optimization_notes"], list):
            raise ValueError("optimization_notes must be a list")
        if not isinstance(data["confidence"], (int, float)):
            raise ValueError("confidence must be a number")

        return {
            "prompt_rewrites": list(data["prompt_rewrites"]),
            "parameter_changes": dict(data["parameter_changes"]),
            "optimization_notes": list(data["optimization_notes"]),
            "rationale": str(data["rationale"]),
            "confidence": float(data["confidence"]),
        }

    def _parse_hypothesis_response(self, response: str) -> dict[str, Any]:
        """Parse the LLM response for hypothesis generation.

        Args:
            response: Raw LLM response string (expected JSON).

        Returns:
            Validated hypothesis dict.

        Raises:
            ValueError: If response is invalid or missing required fields.
            json.JSONDecodeError: If response is not valid JSON.
        """
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")

        required_fields = [
            "hypothesis",
            "metric",
            "baseline_mean",
            "baseline_std",
            "expected_effect",
            "rationale",
        ]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        return {
            "hypothesis": str(data["hypothesis"]),
            "metric": str(data["metric"]),
            "baseline_mean": float(data["baseline_mean"]),
            "baseline_std": float(data["baseline_std"]),
            "expected_effect": float(data["expected_effect"]),
            "rationale": str(data["rationale"]),
        }

    def _agent_heuristic_fallback(
        self,
        performance_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate agent improvement suggestions using heuristic logic.

        Uses AgentEvolution.optimize_model_selection, optimize_tools, and
        optimize_budget as fallback when LLM is unavailable or fails.

        Args:
            performance_data: Performance data dict.

        Returns:
            Heuristic-based improvement suggestion dict.
        """
        # Model selection optimization
        task_type_performance = performance_data.get("task_type_performance", {})
        model_changes = self._fallback_agent_evolution.optimize_model_selection(
            task_type_performance
        )

        # Tool optimization
        tool_usage_stats = performance_data.get("tool_usage_stats", {})
        tool_result = self._fallback_agent_evolution.optimize_tools(tool_usage_stats)

        # Budget optimization
        cost_history = performance_data.get("cost_history", [])
        quality_history = performance_data.get("quality_history", [])
        budget_result = self._fallback_agent_evolution.optimize_budget(
            cost_history, quality_history
        )

        return {
            "model_changes": model_changes,
            "tool_additions": tool_result.get("add", []),
            "tool_removals": tool_result.get("remove", []),
            "budget_recommendation": budget_result.get("recommendation", "maintain"),
            "budget_amount_cents": budget_result.get("suggested_amount_cents", 0),
            "rationale": budget_result.get("reason", "Heuristic-based recommendation"),
            "confidence": 0.5,
            "source": "heuristic",
        }

    def _skill_heuristic_fallback(
        self,
        skill_id: uuid.UUID,
        performance_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate skill improvement suggestions using heuristic logic.

        Uses SkillEvolution.track_performance and compare_versions as fallback
        when LLM is unavailable or fails.

        Args:
            skill_id: The skill UUID.
            performance_data: Performance data dict.

        Returns:
            Heuristic-based skill improvement suggestion dict.
        """
        task_results = performance_data.get("task_results", [])
        scores = [r.get("score", 0.0) for r in task_results] if task_results else []
        avg_score = sum(scores) / len(scores) if scores else 0.0

        # Compare versions if available
        version_a = performance_data.get("version_a")
        version_b = performance_data.get("version_b")
        comparison_notes: list[str] = []

        if version_a and version_b:
            comparison = self._fallback_skill_evolution.compare_versions(
                version_a, version_b
            )
            improvement = comparison.get("improvement_percent", 0.0)
            better = comparison.get("better_version", "equal")
            comparison_notes.append(
                f"Version comparison shows {improvement:.1f}% difference, "
                f"better version: {better}"
            )

        # Generate heuristic suggestions
        optimization_notes = []
        if avg_score < 0.5:
            optimization_notes.append("Performance is below threshold; consider prompt restructuring")
            optimization_notes.append("Review failure cases for common patterns")
        elif avg_score < 0.75:
            optimization_notes.append("Performance is moderate; fine-tune parameters")
        else:
            optimization_notes.append("Performance is good; consider edge case handling")

        optimization_notes.extend(comparison_notes)

        return {
            "prompt_rewrites": [],
            "parameter_changes": {},
            "optimization_notes": optimization_notes,
            "rationale": f"Heuristic analysis based on average score of {avg_score:.2f}",
            "confidence": 0.4,
            "source": "heuristic",
        }

    def _hypothesis_heuristic_fallback(
        self,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a heuristic hypothesis when LLM is unavailable.

        Args:
            context: Context dict with available performance data.

        Returns:
            Heuristic-based hypothesis dict.
        """
        # Extract what we can from context
        performance_data = context.get("performance_data", {})
        quality_history = performance_data.get("quality_history", [])

        if quality_history:
            baseline_mean = sum(quality_history) / len(quality_history)
            # Estimate std from data
            if len(quality_history) > 1:
                variance = sum(
                    (x - baseline_mean) ** 2 for x in quality_history
                ) / (len(quality_history) - 1)
                baseline_std = variance ** 0.5
            else:
                baseline_std = 0.1
        else:
            baseline_mean = 0.7
            baseline_std = 0.15

        # Default hypothesis: improving the weakest component yields 10% gain
        expected_effect = baseline_mean * 0.1

        return {
            "hypothesis": "Optimizing the lowest-performing component will improve overall metric",
            "metric": "success_rate",
            "baseline_mean": baseline_mean,
            "baseline_std": baseline_std,
            "expected_effect": expected_effect,
            "rationale": "Heuristic: targeting the weakest link typically yields the highest marginal gains",
            "source": "heuristic",
        }
