"""Tests for StatisticalAnalyzer - pure stdlib statistics."""

import pytest

from nexus.evolution.statistical import StatisticalAnalyzer


class TestStatisticalAnalyzer:
    """Test suite for StatisticalAnalyzer with deterministic hand-crafted data."""

    @pytest.fixture
    def analyzer(self) -> StatisticalAnalyzer:
        """Create a StatisticalAnalyzer instance."""
        return StatisticalAnalyzer()

    def test_compute_significance_identical_data(self, analyzer: StatisticalAnalyzer) -> None:
        """Identical data should give p_value near 1.0 and is_significant=False."""
        data = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        result = analyzer.compute_significance(data, data)

        assert result["p_value"] > 0.9
        assert result["is_significant"] is False
        assert result["t_statistic"] == 0.0
        assert "degrees_of_freedom" in result
        assert result["alpha"] == 0.05

    def test_compute_significance_clearly_different(self, analyzer: StatisticalAnalyzer) -> None:
        """Clearly different distributions should be detected as significant."""
        control = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]
        treatment = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.compute_significance(control, treatment)

        assert result["is_significant"] is True
        assert result["p_value"] < 0.001
        assert result["t_statistic"] > 0  # treatment > control
        assert result["degrees_of_freedom"] > 0

    def test_compute_significance_insufficient_data(self, analyzer: StatisticalAnalyzer) -> None:
        """Insufficient data returns safe defaults."""
        result = analyzer.compute_significance([1.0], [2.0])

        assert result["p_value"] == 1.0
        assert result["is_significant"] is False

    def test_compute_significance_custom_alpha(self, analyzer: StatisticalAnalyzer) -> None:
        """Custom alpha level is respected."""
        control = [1.0, 1.5, 2.0, 1.3, 1.7, 1.4, 1.6, 1.2, 1.8, 1.1]
        treatment = [2.0, 2.5, 3.0, 2.3, 2.7, 2.4, 2.6, 2.2, 2.8, 2.1]

        # With strict alpha=0.001
        result_strict = analyzer.compute_significance(control, treatment, alpha=0.001)
        # With lenient alpha=0.10
        result_lenient = analyzer.compute_significance(control, treatment, alpha=0.10)

        assert result_strict["alpha"] == 0.001
        assert result_lenient["alpha"] == 0.10
        # Both should detect this clear difference
        assert result_lenient["is_significant"] is True

    def test_compute_significance_zero_variance(self, analyzer: StatisticalAnalyzer) -> None:
        """Zero variance data returns safe defaults."""
        result = analyzer.compute_significance([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])

        assert result["p_value"] == 1.0
        assert result["is_significant"] is False
        assert result["t_statistic"] == 0.0

    def test_detect_trend_upward(self, analyzer: StatisticalAnalyzer) -> None:
        """Clear upward trend should be detected."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        result = analyzer.detect_trend(values)

        assert result["direction"] == "upward"
        assert result["slope"] > 0
        assert result["r_squared"] > 0.99
        assert "intercept" in result

    def test_detect_trend_downward(self, analyzer: StatisticalAnalyzer) -> None:
        """Clear downward trend should be detected."""
        values = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0, 2.0, 1.0]
        result = analyzer.detect_trend(values)

        assert result["direction"] == "downward"
        assert result["slope"] < 0
        assert result["r_squared"] > 0.99

    def test_detect_trend_flat(self, analyzer: StatisticalAnalyzer) -> None:
        """Flat data should be detected as no trend."""
        values = [5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0, 5.0]
        result = analyzer.detect_trend(values)

        assert result["direction"] == "flat"
        assert result["slope"] == 0.0

    def test_detect_trend_single_value(self, analyzer: StatisticalAnalyzer) -> None:
        """Single value returns flat trend."""
        result = analyzer.detect_trend([42.0])

        assert result["direction"] == "flat"
        assert result["slope"] == 0.0
        assert result["intercept"] == 42.0

    def test_detect_trend_r_squared(self, analyzer: StatisticalAnalyzer) -> None:
        """Noisy trend has lower r_squared than perfect trend."""
        perfect = [1.0, 2.0, 3.0, 4.0, 5.0]
        noisy = [1.0, 3.0, 2.0, 4.0, 5.0]

        result_perfect = analyzer.detect_trend(perfect)
        result_noisy = analyzer.detect_trend(noisy)

        assert result_perfect["r_squared"] > result_noisy["r_squared"]

    def test_confidence_interval_contains_mean(self, analyzer: StatisticalAnalyzer) -> None:
        """Confidence interval should contain the sample mean."""
        data = [4.5, 5.0, 5.5, 4.8, 5.2, 5.1, 4.9, 5.3, 4.7, 5.0]
        result = analyzer.compute_confidence_interval(data)

        assert result["lower"] <= result["mean"] <= result["upper"]
        assert result["confidence"] == 0.95
        assert result["sample_size"] == 10
        assert result["std_error"] > 0

    def test_confidence_interval_width_decreases_with_n(self, analyzer: StatisticalAnalyzer) -> None:
        """Larger sample should give narrower confidence interval."""
        small_data = [5.0, 5.1, 4.9, 5.0, 5.2]
        large_data = [5.0, 5.1, 4.9, 5.0, 5.2] * 10

        small_result = analyzer.compute_confidence_interval(small_data)
        large_result = analyzer.compute_confidence_interval(large_data)

        small_width = small_result["upper"] - small_result["lower"]
        large_width = large_result["upper"] - large_result["lower"]
        assert large_width < small_width

    def test_confidence_interval_higher_confidence_wider(self, analyzer: StatisticalAnalyzer) -> None:
        """Higher confidence level should give wider interval."""
        data = [4.5, 5.0, 5.5, 4.8, 5.2, 5.1, 4.9, 5.3, 4.7, 5.0]

        result_90 = analyzer.compute_confidence_interval(data, confidence=0.90)
        result_99 = analyzer.compute_confidence_interval(data, confidence=0.99)

        width_90 = result_90["upper"] - result_90["lower"]
        width_99 = result_99["upper"] - result_99["lower"]
        assert width_99 > width_90

    def test_confidence_interval_single_value(self, analyzer: StatisticalAnalyzer) -> None:
        """Single value has zero-width interval."""
        result = analyzer.compute_confidence_interval([7.0])

        assert result["mean"] == 7.0
        assert result["lower"] == 7.0
        assert result["upper"] == 7.0

    def test_is_significant_improvement_large_effect(self, analyzer: StatisticalAnalyzer) -> None:
        """Large effect size should be detected as significant improvement."""
        control = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]
        treatment = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.is_significant_improvement(control, treatment)

        assert result["is_significant"] is True
        assert result["is_practically_significant"] is True
        assert result["is_improvement"] is True
        assert result["cohens_d"] > 0.8
        assert result["effect_interpretation"] == "large"
        assert result["p_value"] < 0.05

    def test_is_significant_improvement_no_difference(self, analyzer: StatisticalAnalyzer) -> None:
        """Identical distributions should not be an improvement."""
        data = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = analyzer.is_significant_improvement(data, data)

        assert result["is_improvement"] is False
        assert result["is_significant"] is False
        assert result["cohens_d"] == 0.0

    def test_is_significant_improvement_small_effect(self, analyzer: StatisticalAnalyzer) -> None:
        """Small effect with min_effect_size=0.8 should not be practically significant."""
        # High variance data so a small mean difference gives small Cohen's d
        control = [2.0, 4.0, 6.0, 3.0, 5.0, 7.0, 1.0, 8.0, 4.5, 5.5]
        treatment = [2.5, 4.5, 6.5, 3.5, 5.5, 7.5, 1.5, 8.5, 5.0, 6.0]

        result = analyzer.is_significant_improvement(control, treatment, min_effect_size=0.8)

        # Cohen's d should be small (less than 0.8)
        assert abs(result["cohens_d"]) < 0.8
        assert result["is_practically_significant"] is False
        assert result["is_improvement"] is False  # not practically significant enough

    def test_is_significant_improvement_insufficient_data(self, analyzer: StatisticalAnalyzer) -> None:
        """Insufficient data returns safe defaults."""
        result = analyzer.is_significant_improvement([1.0], [2.0])

        assert result["is_significant"] is False
        assert result["is_improvement"] is False
        assert result["effect_interpretation"] == "insufficient_data"

    def test_is_significant_improvement_degradation(self, analyzer: StatisticalAnalyzer) -> None:
        """When treatment is worse, it should not be flagged as improvement."""
        control = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        treatment = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]

        result = analyzer.is_significant_improvement(control, treatment)

        assert result["is_significant"] is True
        assert result["is_improvement"] is False  # treatment is worse
        assert result["cohens_d"] < 0
