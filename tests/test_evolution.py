"""Tests for the Evolution Engine module.

Validates EvolutionObserver, FailureAnalyzer, ImprovementProposer,
EvolutionSandbox, ProposalEvaluator, ChangePromoter, SkillEvolution,
and AgentEvolution functionality.

Tests focus on pure logic methods. DB-dependent async methods are tested
with mock sessions. CRITICAL: All promote/promote_version/promote_candidate
methods MUST raise ValueError when approval_id is None.
"""

import uuid
from datetime import datetime, timezone

import pytest

from nexus.evolution.observer import EvolutionObserver
from nexus.evolution.analyzer import FailureAnalyzer
from nexus.evolution.proposer import ImprovementProposer
from nexus.evolution.sandbox import EvolutionSandbox
from nexus.evolution.evaluator import ProposalEvaluator
from nexus.evolution.promoter import ChangePromoter
from nexus.evolution.skill_evolution import SkillEvolution
from nexus.evolution.agent_evolution import AgentEvolution


@pytest.fixture
def company_id():
    """Provide a fixed company UUID for tests."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


@pytest.fixture
def agent_id():
    """Provide a fixed agent UUID for tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def skill_id():
    """Provide a fixed skill UUID for tests."""
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def proposal_id():
    """Provide a fixed proposal UUID for tests."""
    return uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@pytest.fixture
def approval_id():
    """Provide a fixed approval UUID for tests."""
    return uuid.UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")


# =============================================================================
# EvolutionObserver Tests
# =============================================================================


class TestEvolutionObserver:
    """Tests for EvolutionObserver."""

    @pytest.mark.asyncio
    async def test_track_execution(self, company_id, agent_id):
        """track_execution records data in memory."""
        observer = EvolutionObserver()
        task_id = uuid.uuid4()

        record = await observer.track_execution(
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
            outcome="success",
            duration_seconds=5.0,
            cost_cents=50,
            metadata={"tool": "search"},
        )

        assert record["outcome"] == "success"
        assert record["duration_seconds"] == 5.0
        assert record["cost_cents"] == 50
        assert record["metadata"] == {"tool": "search"}
        assert len(observer._executions) == 1

    def test_detect_patterns_recurring_failures(self, company_id, agent_id):
        """detect_patterns finds recurring failures."""
        observer = EvolutionObserver()
        executions = [
            {"company_id": str(company_id), "agent_id": str(agent_id), "outcome": "failure", "duration_seconds": 5, "cost_cents": 10},
            {"company_id": str(company_id), "agent_id": str(agent_id), "outcome": "failure", "duration_seconds": 6, "cost_cents": 12},
            {"company_id": str(company_id), "agent_id": str(agent_id), "outcome": "failure", "duration_seconds": 7, "cost_cents": 15},
        ]

        patterns = observer.detect_patterns(company_id, executions)
        assert len(patterns) >= 1
        assert patterns[0]["pattern_type"] == "recurring_failure"
        assert patterns[0]["occurrences"] == 3

    def test_detect_patterns_empty(self, company_id):
        """detect_patterns returns empty for no data."""
        observer = EvolutionObserver()
        patterns = observer.detect_patterns(company_id, [])
        assert patterns == []

    def test_detect_anomalies(self):
        """detect_anomalies flags values outside threshold."""
        observer = EvolutionObserver()
        values = [10.0, 11.0, 9.0, 10.5, 50.0, 10.0, 9.5]
        anomalies = observer.detect_anomalies(values, threshold_std=2.0)
        assert 4 in anomalies  # 50.0 is the anomaly

    def test_detect_anomalies_empty(self):
        """detect_anomalies handles empty input."""
        observer = EvolutionObserver()
        assert observer.detect_anomalies([]) == []
        assert observer.detect_anomalies([5.0]) == []

    def test_detect_anomalies_no_variance(self):
        """detect_anomalies handles zero variance."""
        observer = EvolutionObserver()
        assert observer.detect_anomalies([5.0, 5.0, 5.0]) == []

    def test_classify_pattern_systemic(self):
        """classify_pattern returns 'systemic' for 3+ occurrences with spread."""
        observer = EvolutionObserver()
        pattern = {"occurrences": 5, "examples": [{"a": 1}, {"a": 2}, {"a": 3}]}
        assert observer.classify_pattern(pattern) == "systemic"

    def test_classify_pattern_one_off(self):
        """classify_pattern returns 'one_off' for few occurrences."""
        observer = EvolutionObserver()
        pattern = {"occurrences": 1, "examples": [{"a": 1}]}
        assert observer.classify_pattern(pattern) == "one_off"


# =============================================================================
# FailureAnalyzer Tests
# =============================================================================


class TestFailureAnalyzer:
    """Tests for FailureAnalyzer."""

    def test_root_cause_analysis(self):
        """root_cause_analysis groups failures by common factors."""
        analyzer = FailureAnalyzer()
        failures = [
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web", "error": "timeout", "timestamp": "2024-01-01"},
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web", "error": "timeout", "timestamp": "2024-01-02"},
            {"agent_id": "agent1", "task_type": "write", "tool_used": "file", "error": "perm", "timestamp": "2024-01-03"},
        ]

        results = analyzer.root_cause_analysis(failures)
        assert len(results) > 0
        # agent1 appears 3 times
        agent_factors = [r for r in results if r["factor_type"] == "agent_id" and r["factor_value"] == "agent1"]
        assert len(agent_factors) == 1
        assert agent_factors[0]["occurrence_count"] == 3
        assert agent_factors[0]["percentage"] == 100.0

    def test_root_cause_analysis_empty(self):
        """root_cause_analysis returns empty for no failures."""
        analyzer = FailureAnalyzer()
        assert analyzer.root_cause_analysis([]) == []

    def test_extract_success_factors(self):
        """extract_success_factors identifies commonalities."""
        analyzer = FailureAnalyzer()
        successes = [
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web"},
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web"},
            {"agent_id": "agent2", "task_type": "search", "tool_used": "api"},
        ]

        factors = analyzer.extract_success_factors(successes)
        assert len(factors) > 0
        # task_type:search appears in all 3 (100%)
        search_factors = [f for f in factors if f["factor"] == "task_type:search"]
        assert len(search_factors) == 1
        assert search_factors[0]["frequency"] == 1.0

    def test_compare_outcomes(self):
        """compare_outcomes finds differentiators."""
        analyzer = FailureAnalyzer()
        successes = [
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web"},
        ]
        failures = [
            {"agent_id": "agent2", "task_type": "write", "tool_used": "file"},
        ]

        result = analyzer.compare_outcomes(successes, failures)
        assert "common_in_success" in result
        assert "common_in_failure" in result
        assert "differentiators" in result

    def test_identify_bottlenecks(self):
        """identify_bottlenecks sorts stages by avg duration."""
        analyzer = FailureAnalyzer()
        history = [
            {"stage": "planning", "duration_seconds": 10},
            {"stage": "planning", "duration_seconds": 12},
            {"stage": "execution", "duration_seconds": 30},
            {"stage": "execution", "duration_seconds": 25},
            {"stage": "review", "duration_seconds": 5},
        ]

        bottlenecks = analyzer.identify_bottlenecks(history)
        assert bottlenecks[0]["stage"] == "execution"
        assert bottlenecks[0]["avg_duration"] == 27.5
        assert bottlenecks[0]["count"] == 2
        assert bottlenecks[-1]["stage"] == "review"

    def test_cost_effectiveness_analysis(self):
        """cost_effectiveness_analysis identifies best/worst approaches."""
        analyzer = FailureAnalyzer()
        executions = [
            {"approach": "gpt4", "cost_cents": 100, "quality_score": 0.9},
            {"approach": "gpt4", "cost_cents": 120, "quality_score": 0.85},
            {"approach": "gpt35", "cost_cents": 10, "quality_score": 0.5},
            {"approach": "gpt35", "cost_cents": 12, "quality_score": 0.45},
        ]

        result = analyzer.cost_effectiveness_analysis(executions)
        assert "avg_cost_per_quality" in result
        assert result["best_approach"] == "gpt35"  # Lower cost per quality unit
        assert result["worst_approach"] == "gpt4"  # Higher cost per quality unit


# =============================================================================
# ImprovementProposer Tests
# =============================================================================


class TestImprovementProposer:
    """Tests for ImprovementProposer."""

    def test_propose_skill_improvement(self, company_id, skill_id):
        """propose_skill_improvement generates a valid proposal."""
        proposer = ImprovementProposer()
        failure_analysis = [
            {"factor_type": "agent_id", "factor_value": "agent1", "occurrence_count": 5, "percentage": 80.0},
        ]

        proposal = proposer.propose_skill_improvement(company_id, skill_id, failure_analysis)
        assert proposal["proposal_type"] == "skill_improvement"
        assert proposal["title"]
        assert proposal["description"]
        assert 0 <= proposal["confidence"] <= 1
        assert proposal["risk_level"] in ("low", "medium", "high")
        assert isinstance(proposal["estimated_cost_cents"], int)
        assert proposal["proposed_by"] == "evolution_engine"
        assert proposal["proposed_at"]

    def test_propose_workflow_change(self, company_id):
        """propose_workflow_change generates a valid proposal."""
        proposer = ImprovementProposer()
        bottleneck_analysis = [
            {"stage": "execution", "avg_duration": 30.0, "count": 10},
            {"stage": "planning", "avg_duration": 5.0, "count": 10},
        ]

        proposal = proposer.propose_workflow_change(company_id, bottleneck_analysis)
        assert proposal["proposal_type"] == "workflow_change"
        assert proposal["proposed_by"] == "evolution_engine"
        assert proposal["confidence"] > 0

    def test_propose_agent_config(self, company_id, agent_id):
        """propose_agent_config generates a valid proposal."""
        proposer = ImprovementProposer()
        performance_data = {"avg_quality": 0.5, "avg_cost_cents": 200, "avg_duration_seconds": 45}

        proposal = proposer.propose_agent_config(company_id, agent_id, performance_data)
        assert proposal["proposal_type"] == "agent_config"
        assert proposal["proposed_by"] == "evolution_engine"

    def test_propose_org_change(self, company_id):
        """propose_org_change generates a valid proposal."""
        proposer = ImprovementProposer()
        performance_data = {"overall_quality": 0.7}
        org_structure = {
            "agents": [
                {"id": "a1", "task_count": 15, "capacity": 10},
                {"id": "a2", "task_count": 2, "capacity": 10},
            ]
        }

        proposal = proposer.propose_org_change(company_id, performance_data, org_structure)
        assert proposal["proposal_type"] == "org_change"
        assert proposal["risk_level"] == "high"
        assert proposal["proposed_by"] == "evolution_engine"


# =============================================================================
# EvolutionSandbox Tests
# =============================================================================


class TestEvolutionSandbox:
    """Tests for EvolutionSandbox."""

    def test_create_sandbox(self, proposal_id):
        """create_sandbox returns a valid sandbox_id."""
        sandbox = EvolutionSandbox()
        sandbox_id = sandbox.create_sandbox(proposal_id, {"model": "gpt-4"})
        assert isinstance(sandbox_id, uuid.UUID)
        assert str(sandbox_id) in sandbox._sandboxes

    @pytest.mark.asyncio
    async def test_run_benchmark(self, proposal_id):
        """run_benchmark returns results for test cases."""
        sandbox = EvolutionSandbox()
        sandbox_id = sandbox.create_sandbox(proposal_id, {"model": "gpt-4"})

        test_cases = [
            {"id": "test1", "expected_score": 0.85, "expected_duration_ms": 100},
            {"id": "test2", "expected_score": 0.9, "expected_duration_ms": 120},
        ]

        results = await sandbox.run_benchmark(sandbox_id, test_cases)
        assert len(results) == 2
        assert results[0]["test_case_id"] == "test1"
        assert results[0]["score"] == 0.85

    def test_compare_with_baseline(self):
        """compare_with_baseline calculates improvement correctly."""
        sandbox = EvolutionSandbox()
        sandbox_results = [
            {"score": 0.9, "duration_ms": 80},
            {"score": 0.85, "duration_ms": 90},
        ]
        baseline_results = [
            {"score": 0.7, "duration_ms": 100},
            {"score": 0.75, "duration_ms": 110},
        ]

        comparison = sandbox.compare_with_baseline(sandbox_results, baseline_results)
        assert comparison["improvement_percent"] > 0
        assert "dimensions" in comparison
        assert "quality" in comparison["dimensions"]
        assert "speed" in comparison["dimensions"]

    def test_enforce_resource_limits(self, proposal_id):
        """enforce_resource_limits updates sandbox config."""
        sandbox = EvolutionSandbox()
        sandbox_id = sandbox.create_sandbox(proposal_id, {})
        sandbox.enforce_resource_limits(sandbox_id, max_cost_cents=500, max_duration_seconds=60)

        config = sandbox._sandboxes[str(sandbox_id)]
        assert config["max_cost_cents"] == 500
        assert config["max_duration_seconds"] == 60

    def test_cleanup(self, proposal_id):
        """cleanup removes sandbox from tracking."""
        sandbox = EvolutionSandbox()
        sandbox_id = sandbox.create_sandbox(proposal_id, {})
        assert str(sandbox_id) in sandbox._sandboxes

        sandbox.cleanup(sandbox_id)
        assert str(sandbox_id) not in sandbox._sandboxes


# =============================================================================
# ProposalEvaluator Tests
# =============================================================================


class TestProposalEvaluator:
    """Tests for ProposalEvaluator."""

    def test_evaluate_improvement(self, proposal_id):
        """evaluate detects significant improvement."""
        evaluator = ProposalEvaluator()
        # Use 100 samples so significance threshold (2/sqrt(100)*100=20%) is met
        sandbox_results = [{"score": 0.9, "duration_ms": 80}] * 100
        baseline_results = [{"score": 0.7, "duration_ms": 120}] * 100

        result = evaluator.evaluate(proposal_id, sandbox_results, baseline_results)
        assert result["passed"] is True
        assert result["improvement_percent"] > 5.0
        assert "dimensions" in result
        assert result["recommendation"]

    def test_evaluate_no_improvement(self, proposal_id):
        """evaluate rejects when no improvement."""
        evaluator = ProposalEvaluator()
        sandbox_results = [
            {"score": 0.7, "duration_ms": 100},
        ]
        baseline_results = [
            {"score": 0.7, "duration_ms": 100},
        ]

        result = evaluator.evaluate(proposal_id, sandbox_results, baseline_results)
        assert result["passed"] is False

    def test_check_significance_sufficient(self):
        """check_significance returns True for significant improvement."""
        evaluator = ProposalEvaluator()
        # With 100 samples, threshold is 2/sqrt(100)*100 = 20%
        assert evaluator.check_significance(25.0, 100) is True

    def test_check_significance_insufficient(self):
        """check_significance returns False for insignificant improvement."""
        evaluator = ProposalEvaluator()
        # With 4 samples, threshold is 2/sqrt(4)*100 = 100%
        assert evaluator.check_significance(5.0, 4) is False

    def test_check_promotion_criteria(self):
        """check_promotion_criteria validates passed and threshold."""
        evaluator = ProposalEvaluator()
        assert evaluator.check_promotion_criteria({"passed": True, "improvement_percent": 10.0}) is True
        assert evaluator.check_promotion_criteria({"passed": True, "improvement_percent": 3.0}) is False
        assert evaluator.check_promotion_criteria({"passed": False, "improvement_percent": 10.0}) is False

    @pytest.mark.asyncio
    async def test_reject_with_explanation(self, proposal_id):
        """reject_with_explanation returns rejection record."""
        evaluator = ProposalEvaluator()
        result = await evaluator.reject_with_explanation(proposal_id, ["Low improvement", "Safety concern"])
        assert result["status"] == "rejected"
        assert len(result["rejection_reasons"]) == 2


# =============================================================================
# ChangePromoter Tests - Governance Gate is CRITICAL
# =============================================================================


class TestChangePromoter:
    """Tests for ChangePromoter - GOVERNANCE GATE ENFORCEMENT."""

    @pytest.mark.asyncio
    async def test_promote_requires_approval_id(self, proposal_id):
        """CRITICAL: promote raises ValueError if approval_id is None."""
        promoter = ChangePromoter()
        with pytest.raises(ValueError, match="Approval required: approval_id must not be None"):
            await promoter.promote(proposal_id, None)

    @pytest.mark.asyncio
    async def test_promote_with_approval(self, proposal_id, approval_id):
        """promote succeeds with valid approval_id."""
        promoter = ChangePromoter()
        result = await promoter.promote(proposal_id, approval_id)
        assert result["status"] == "promoted"
        assert result["approval_id"] == str(approval_id)

    def test_apply_change(self):
        """apply_change returns applied status."""
        promoter = ChangePromoter()
        result = promoter.apply_change({"proposal_type": "skill_improvement"})
        assert result["applied"] is True
        assert result["change_id"]
        assert result["applied_at"]

    def test_configure_canary(self, proposal_id):
        """configure_canary sets up gradual rollout."""
        promoter = ChangePromoter()
        canary = promoter.configure_canary(proposal_id, percentage=10)
        assert canary["percentage"] == 10
        assert canary["status"] == "active"

    def test_monitor_canary_healthy(self, proposal_id):
        """monitor_canary reports healthy when metrics are good."""
        promoter = ChangePromoter()
        metrics = [{"score": 0.9}, {"score": 0.85}, {"score": 0.88}]
        result = promoter.monitor_canary(proposal_id, metrics)
        assert result["status"] == "healthy"
        assert result["should_rollback"] is False

    def test_monitor_canary_degrading(self, proposal_id):
        """monitor_canary detects degradation."""
        promoter = ChangePromoter()
        metrics = [
            {"score": 0.3, "error": True},
            {"score": 0.2, "error": True},
            {"score": 0.4, "error": False},
        ]
        result = promoter.monitor_canary(proposal_id, metrics)
        assert result["status"] == "degrading"
        assert result["should_rollback"] is True

    @pytest.mark.asyncio
    async def test_rollback(self, proposal_id):
        """rollback returns rolled_back status."""
        promoter = ChangePromoter()
        result = await promoter.rollback(proposal_id, "Performance degraded")
        assert result["status"] == "rolled_back"
        assert result["reason"] == "Performance degraded"


# =============================================================================
# SkillEvolution Tests - Governance Gate is CRITICAL
# =============================================================================


class TestSkillEvolution:
    """Tests for SkillEvolution - GOVERNANCE GATE ENFORCEMENT."""

    @pytest.mark.asyncio
    async def test_create_version(self, company_id, skill_id):
        """create_version creates a new skill version."""
        evo = SkillEvolution()
        version = await evo.create_version(company_id, skill_id, "You are a helpful assistant.")
        assert version["version_number"] == 1
        assert version["prompt_template"] == "You are a helpful assistant."
        assert version["is_active"] is False

    @pytest.mark.asyncio
    async def test_create_multiple_versions(self, company_id, skill_id):
        """create_version increments version number."""
        evo = SkillEvolution()
        v1 = await evo.create_version(company_id, skill_id, "template v1")
        v2 = await evo.create_version(company_id, skill_id, "template v2")
        assert v1["version_number"] == 1
        assert v2["version_number"] == 2

    def test_track_performance(self, company_id, skill_id):
        """track_performance updates and returns score."""
        evo = SkillEvolution()
        # Create a version first (sync workaround: add directly)
        version_id = uuid.uuid4()
        evo._versions.append({
            "id": str(version_id),
            "company_id": str(company_id),
            "skill_id": str(skill_id),
            "version_number": 1,
            "prompt_template": "test",
            "performance_score": None,
            "is_active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

        task_results = [{"score": 0.8}, {"score": 0.9}, {"score": 0.7}]
        score = evo.track_performance(version_id, task_results)
        assert abs(score - 0.8) < 0.001

    def test_compare_versions(self):
        """compare_versions returns improvement metrics."""
        evo = SkillEvolution()
        version_a = {"id": "a", "version_number": 1, "performance_score": 0.7}
        version_b = {"id": "b", "version_number": 2, "performance_score": 0.84}

        comparison = evo.compare_versions(version_a, version_b)
        assert comparison["better_version"] == "b"
        assert comparison["improvement_percent"] == pytest.approx(20.0)

    @pytest.mark.asyncio
    async def test_promote_version_requires_approval(self, company_id, skill_id):
        """CRITICAL: promote_version raises ValueError if approval_id is None."""
        evo = SkillEvolution()
        version = await evo.create_version(company_id, skill_id, "template")
        version_id = uuid.UUID(version["id"])

        with pytest.raises(ValueError, match="Approval required: approval_id must not be None"):
            await evo.promote_version(version_id, None)

    @pytest.mark.asyncio
    async def test_promote_version_with_approval(self, company_id, skill_id, approval_id):
        """promote_version succeeds with valid approval_id."""
        evo = SkillEvolution()
        version = await evo.create_version(company_id, skill_id, "template")
        version_id = uuid.UUID(version["id"])

        result = await evo.promote_version(version_id, approval_id)
        assert result["is_active"] is True
        assert result["approval_id"] == str(approval_id)

    @pytest.mark.asyncio
    async def test_rollback_version(self, company_id, skill_id, approval_id):
        """rollback_version reactivates previous version."""
        evo = SkillEvolution()
        v1 = await evo.create_version(company_id, skill_id, "template v1")
        v2 = await evo.create_version(company_id, skill_id, "template v2")
        v2_id = uuid.UUID(v2["id"])

        # Promote v2
        await evo.promote_version(v2_id, approval_id)

        # Rollback
        result = await evo.rollback_version(skill_id, company_id)
        assert result["version_number"] == 1
        assert result["is_active"] is True

    @pytest.mark.asyncio
    async def test_get_version_history(self, company_id, skill_id):
        """get_version_history returns all versions sorted."""
        evo = SkillEvolution()
        await evo.create_version(company_id, skill_id, "v1")
        await evo.create_version(company_id, skill_id, "v2")

        history = await evo.get_version_history(skill_id, company_id)
        assert len(history) == 2
        assert history[0]["version_number"] == 1
        assert history[1]["version_number"] == 2


# =============================================================================
# AgentEvolution Tests - Governance Gate is CRITICAL
# =============================================================================


class TestAgentEvolution:
    """Tests for AgentEvolution - GOVERNANCE GATE ENFORCEMENT."""

    @pytest.mark.asyncio
    async def test_create_candidate(self, company_id, agent_id):
        """create_candidate creates a new agent version."""
        evo = AgentEvolution()
        config = {"model": "gpt-4", "temperature": 0.7}
        version = await evo.create_candidate(company_id, agent_id, config)
        assert version["version_number"] == 1
        assert version["config_snapshot"] == config
        assert version["is_active"] is False

    def test_optimize_model_selection(self):
        """optimize_model_selection recommends best model per task type."""
        evo = AgentEvolution()
        task_perf = {
            "summarization": {"gpt-4": 0.95, "gpt-3.5": 0.7, "claude": 0.9},
            "code_generation": {"gpt-4": 0.85, "gpt-3.5": 0.6, "claude": 0.92},
        }

        recommendations = evo.optimize_model_selection(task_perf)
        assert recommendations["summarization"] == "gpt-4"
        assert recommendations["code_generation"] == "claude"

    def test_optimize_tools(self):
        """optimize_tools recommends tool changes."""
        evo = AgentEvolution()
        stats = {
            "web_search": {"usage_count": 100, "success_rate": 0.9},
            "broken_tool": {"usage_count": 20, "success_rate": 0.1},
            "unused_tool": {"usage_count": 0, "success_rate": 0.0},
            "new_tool": {"usage_count": 0, "success_rate": 0.0, "suggested": True},
        }

        result = evo.optimize_tools(stats)
        assert "web_search" in result["keep"]
        assert "broken_tool" in result["remove"]
        assert "new_tool" in result["add"]

    def test_optimize_budget_increase(self):
        """optimize_budget recommends increase for low quality."""
        evo = AgentEvolution()
        costs = [100.0, 120.0, 110.0]
        quality = [0.3, 0.35, 0.4]

        result = evo.optimize_budget(costs, quality)
        assert result["recommendation"] == "increase"
        assert result["suggested_amount_cents"] > 0

    def test_optimize_budget_decrease(self):
        """optimize_budget recommends decrease for high quality, high cost."""
        evo = AgentEvolution()
        costs = [500.0, 600.0, 550.0]
        quality = [0.9, 0.92, 0.88]

        result = evo.optimize_budget(costs, quality)
        assert result["recommendation"] == "decrease"
        assert result["suggested_amount_cents"] > 0

    def test_optimize_budget_maintain(self):
        """optimize_budget recommends maintain for balanced state."""
        evo = AgentEvolution()
        costs = [200.0, 210.0, 190.0]
        quality = [0.75, 0.72, 0.78]

        result = evo.optimize_budget(costs, quality)
        assert result["recommendation"] == "maintain"

    @pytest.mark.asyncio
    async def test_promote_candidate_requires_approval(self, company_id, agent_id):
        """CRITICAL: promote_candidate raises ValueError if approval_id is None."""
        evo = AgentEvolution()
        version = await evo.create_candidate(company_id, agent_id, {"model": "gpt-4"})
        version_id = uuid.UUID(version["id"])

        with pytest.raises(ValueError, match="Approval required: approval_id must not be None"):
            await evo.promote_candidate(version_id, None)

    @pytest.mark.asyncio
    async def test_promote_candidate_with_approval(self, company_id, agent_id, approval_id):
        """promote_candidate succeeds with valid approval_id."""
        evo = AgentEvolution()
        version = await evo.create_candidate(company_id, agent_id, {"model": "gpt-4"})
        version_id = uuid.UUID(version["id"])

        result = await evo.promote_candidate(version_id, approval_id)
        assert result["is_active"] is True
        assert result["approval_id"] == str(approval_id)

    @pytest.mark.asyncio
    async def test_get_evolution_history(self, company_id, agent_id):
        """get_evolution_history returns all versions sorted."""
        evo = AgentEvolution()
        await evo.create_candidate(company_id, agent_id, {"v": 1})
        await evo.create_candidate(company_id, agent_id, {"v": 2})

        history = await evo.get_evolution_history(agent_id, company_id)
        assert len(history) == 2
        assert history[0]["version_number"] == 1
        assert history[1]["version_number"] == 2
