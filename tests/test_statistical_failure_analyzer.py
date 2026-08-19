"""Tests for StatisticalFailureAnalyzer - wiring evolution analyzer to statistics."""

import pytest

from nexus.evolution.analyzer import FailureAnalyzer, StatisticalFailureAnalyzer


class TestStatisticalFailureAnalyzer:
    """Test suite for StatisticalFailureAnalyzer with deterministic data."""

    @pytest.fixture
    def analyzer(self) -> StatisticalFailureAnalyzer:
        """Create a StatisticalFailureAnalyzer instance."""
        return StatisticalFailureAnalyzer()

    # =========================================================================
    # Inheritance Tests
    # =========================================================================

    def test_isinstance_of_failure_analyzer(self) -> None:
        """StatisticalFailureAnalyzer is a subclass of FailureAnalyzer."""
        analyzer = StatisticalFailureAnalyzer()
        assert isinstance(analyzer, FailureAnalyzer)

    def test_inherited_root_cause_analysis(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Inherited root_cause_analysis still works correctly."""
        failures = [
            {
                "agent_id": "agent1",
                "task_type": "search",
                "tool_used": "web",
                "error": "timeout",
                "timestamp": "2024-01-01",
            },
            {
                "agent_id": "agent1",
                "task_type": "search",
                "tool_used": "web",
                "error": "timeout",
                "timestamp": "2024-01-02",
            },
            {
                "agent_id": "agent1",
                "task_type": "write",
                "tool_used": "file",
                "error": "perm",
                "timestamp": "2024-01-03",
            },
        ]

        results = analyzer.root_cause_analysis(failures)
        assert len(results) > 0
        agent_factors = [
            r for r in results if r["factor_type"] == "agent_id" and r["factor_value"] == "agent1"
        ]
        assert len(agent_factors) == 1
        assert agent_factors[0]["occurrence_count"] == 3

    def test_inherited_extract_success_factors(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Inherited extract_success_factors still works correctly."""
        successes = [
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web"},
            {"agent_id": "agent1", "task_type": "search", "tool_used": "web"},
            {"agent_id": "agent2", "task_type": "search", "tool_used": "api"},
        ]

        factors = analyzer.extract_success_factors(successes)
        assert len(factors) > 0
        search_factors = [f for f in factors if f["factor"] == "task_type:search"]
        assert len(search_factors) == 1
        assert search_factors[0]["frequency"] == 1.0

    # =========================================================================
    # is_significant_pattern Tests
    # =========================================================================

    def test_is_significant_pattern_clearly_different(
        self, analyzer: StatisticalFailureAnalyzer
    ) -> None:
        """Clearly different pattern vs baseline is detected as significant."""
        baseline = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]
        pattern = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.is_significant_pattern(pattern, baseline)

        assert result["is_significant"] is True
        assert result["p_value"] < 0.05
        assert "t_statistic" in result
        assert "degrees_of_freedom" in result
        assert result["alpha"] == 0.05

    def test_is_significant_pattern_similar_data(
        self, analyzer: StatisticalFailureAnalyzer
    ) -> None:
        """Similar pattern and baseline should not be significant."""
        baseline = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        pattern = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.is_significant_pattern(pattern, baseline)

        assert result["is_significant"] is False
        assert result["p_value"] > 0.05

    # =========================================================================
    # trend_analysis Tests
    # =========================================================================

    def test_trend_analysis_upward(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Detects upward trend in failure rates."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]

        result = analyzer.trend_analysis(values)

        assert result["direction"] == "upward"
        assert result["slope"] > 0
        assert result["r_squared"] > 0.99
        assert "intercept" in result

    def test_trend_analysis_downward(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Detects downward trend in failure rates."""
        values = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]

        result = analyzer.trend_analysis(values)

        assert result["direction"] == "downward"
        assert result["slope"] < 0
        assert result["r_squared"] > 0.99

    def test_trend_analysis_flat(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Detects flat trend (no directional change)."""
        values = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]

        result = analyzer.trend_analysis(values)

        assert result["direction"] == "flat"
        assert result["slope"] == 0.0

    # =========================================================================
    # compare_periods Tests
    # =========================================================================

    def test_compare_periods_improvement(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Detects significant improvement between periods."""
        period_a = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]
        period_b = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.compare_periods(period_a, period_b)

        assert result["is_significant"] is True
        assert result["is_practically_significant"] is True
        assert result["is_improvement"] is True
        assert result["cohens_d"] > 0.8
        assert result["effect_interpretation"] == "large"
        assert result["p_value"] < 0.05

    def test_compare_periods_no_improvement(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """No improvement when periods are identical."""
        data = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.compare_periods(data, data)

        assert result["is_improvement"] is False
        assert result["is_significant"] is False
        assert result["cohens_d"] == 0.0

    # =========================================================================
    # confidence_interval_for_rate Tests
    # =========================================================================

    def test_confidence_interval_for_rate_valid(self, analyzer: StatisticalFailureAnalyzer) -> None:
        """Returns a valid confidence interval containing the mean."""
        failure_counts = [4.5, 5.0, 5.5, 4.8, 5.2, 5.1, 4.9, 5.3, 4.7, 5.0]

        result = analyzer.confidence_interval_for_rate(failure_counts)

        assert result["lower"] <= result["mean"] <= result["upper"]
        assert result["confidence"] == 0.95
        assert result["sample_size"] == 10
        assert result["std_error"] > 0
