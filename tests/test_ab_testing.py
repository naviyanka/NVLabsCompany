"""Tests for ABTestFramework - experiment design, execution, and early stopping."""

import pytest

from nexus.evolution.ab_testing import ABTestFramework
from nexus.evolution.statistical import StatisticalAnalyzer


class TestABTestFramework:
    """Test suite for ABTestFramework with deterministic hand-crafted data."""

    @pytest.fixture
    def framework(self) -> ABTestFramework:
        """Create an ABTestFramework instance."""
        return ABTestFramework()

    @pytest.fixture
    def framework_with_analyzer(self) -> ABTestFramework:
        """Create an ABTestFramework with explicit StatisticalAnalyzer."""
        analyzer = StatisticalAnalyzer()
        return ABTestFramework(statistical_analyzer=analyzer)

    def test_design_test_returns_positive_sample_size(self, framework: ABTestFramework) -> None:
        """design_test should return a positive sample size."""
        result = framework.design_test(
            baseline_mean=50.0,
            baseline_std=10.0,
            min_detectable_effect=5.0,
        )

        assert result["sample_size_per_group"] > 0
        assert result["total_sample_size"] == result["sample_size_per_group"] * 2
        assert result["alpha"] == 0.05
        assert result["power"] == 0.8

    def test_design_test_larger_effect_needs_fewer_samples(self, framework: ABTestFramework) -> None:
        """Larger detectable effect requires fewer samples."""
        result_small = framework.design_test(
            baseline_mean=50.0,
            baseline_std=10.0,
            min_detectable_effect=1.0,
        )
        result_large = framework.design_test(
            baseline_mean=50.0,
            baseline_std=10.0,
            min_detectable_effect=5.0,
        )

        assert result_small["sample_size_per_group"] > result_large["sample_size_per_group"]

    def test_design_test_higher_power_needs_more_samples(self, framework: ABTestFramework) -> None:
        """Higher power requires more samples."""
        result_low_power = framework.design_test(
            baseline_mean=50.0,
            baseline_std=10.0,
            min_detectable_effect=5.0,
            power=0.7,
        )
        result_high_power = framework.design_test(
            baseline_mean=50.0,
            baseline_std=10.0,
            min_detectable_effect=5.0,
            power=0.95,
        )

        assert result_high_power["sample_size_per_group"] > result_low_power["sample_size_per_group"]

    def test_design_test_zero_std(self, framework: ABTestFramework) -> None:
        """Zero standard deviation returns zero sample size."""
        result = framework.design_test(
            baseline_mean=50.0,
            baseline_std=0.0,
            min_detectable_effect=5.0,
        )

        assert result["sample_size_per_group"] == 0
        assert result["total_sample_size"] == 0

    def test_design_test_zero_effect(self, framework: ABTestFramework) -> None:
        """Zero min detectable effect returns zero sample size."""
        result = framework.design_test(
            baseline_mean=50.0,
            baseline_std=10.0,
            min_detectable_effect=0.0,
        )

        assert result["sample_size_per_group"] == 0

    def test_run_test_identical_data_inconclusive(self, framework: ABTestFramework) -> None:
        """Identical data should return 'inconclusive' verdict."""
        data = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        result = framework.run_test(data, data)

        assert result["verdict"] == "inconclusive"
        assert result["p_value"] > 0.05
        assert "confidence_interval" in result
        assert "lower" in result["confidence_interval"]
        assert "upper" in result["confidence_interval"]
        assert "effect_size" in result
        assert "power_estimate" in result

    def test_run_test_clearly_improved(self, framework: ABTestFramework) -> None:
        """Clearly better treatment should return 'improved' verdict."""
        control = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]
        treatment = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = framework.run_test(control, treatment)

        assert result["verdict"] == "improved"
        assert result["p_value"] < 0.001
        assert result["effect_size"] > 0.8
        assert result["mean_difference"] > 0
        assert result["treatment_mean"] > result["control_mean"]

    def test_run_test_clearly_degraded(self, framework: ABTestFramework) -> None:
        """Clearly worse treatment should return 'degraded' verdict."""
        control = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        treatment = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]

        result = framework.run_test(control, treatment)

        assert result["verdict"] == "degraded"
        assert result["p_value"] < 0.001
        assert result["mean_difference"] < 0

    def test_run_test_insufficient_data(self, framework: ABTestFramework) -> None:
        """Insufficient data returns inconclusive with safe defaults."""
        result = framework.run_test([1.0], [2.0])

        assert result["verdict"] == "inconclusive"
        assert result["p_value"] == 1.0

    def test_run_test_confidence_interval_structure(self, framework: ABTestFramework) -> None:
        """Confidence interval has lower and upper bounds."""
        control = [2.0, 2.5, 3.0, 2.3, 2.7, 2.4, 2.6, 2.2, 2.8, 2.1]
        treatment = [4.0, 4.5, 5.0, 4.3, 4.7, 4.4, 4.6, 4.2, 4.8, 4.1]

        result = framework.run_test(control, treatment)

        ci = result["confidence_interval"]
        assert ci["lower"] < ci["upper"]
        # CI should contain the mean difference for clearly different groups
        assert ci["lower"] > 0  # treatment is clearly better

    def test_early_stopping_first_look_stricter_alpha(self, framework: ABTestFramework) -> None:
        """First look should have stricter (smaller) alpha than final look."""
        control = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]
        treatment = [5.5, 5.6, 5.4, 5.5, 5.7, 5.3, 5.5, 5.6, 5.4, 5.5]

        result_early = framework.early_stopping(
            control, treatment, num_looks=5, current_look=1
        )
        result_late = framework.early_stopping(
            control, treatment, num_looks=5, current_look=5
        )

        assert result_early["adjusted_alpha"] < result_late["adjusted_alpha"]
        assert result_early["information_fraction"] == 0.2
        assert result_late["information_fraction"] == 1.0

    def test_early_stopping_final_look_uses_full_alpha(self, framework: ABTestFramework) -> None:
        """At the final look, adjusted alpha equals the overall alpha."""
        control = [5.0, 5.1, 4.9, 5.0, 5.2]
        treatment = [5.5, 5.6, 5.4, 5.5, 5.7]

        result = framework.early_stopping(
            control, treatment, num_looks=3, current_look=3, alpha=0.05
        )

        assert result["adjusted_alpha"] == 0.05
        assert result["num_looks"] == 3
        assert result["current_look"] == 3

    def test_early_stopping_clear_difference_stops(self, framework: ABTestFramework) -> None:
        """Extremely clear difference should trigger stopping even early on."""
        control = [1.0, 1.1, 0.9, 1.0, 1.2, 0.8, 1.0, 1.1, 0.9, 1.0]
        treatment = [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0]

        result = framework.early_stopping(
            control, treatment, num_looks=5, current_look=2
        )

        # With such a massive difference, even early stopping should trigger
        assert result["should_stop"] is True
        assert result["verdict"] == "improved"

    def test_early_stopping_no_difference_continues(self, framework: ABTestFramework) -> None:
        """No difference should not trigger stopping."""
        data = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = framework.early_stopping(
            data, data, num_looks=5, current_look=2
        )

        assert result["should_stop"] is False
        assert result["verdict"] == "continue"

    def test_early_stopping_last_look_inconclusive(self, framework: ABTestFramework) -> None:
        """At last look with no significance, verdict is inconclusive."""
        data = [5.0, 5.1, 4.9, 5.0, 5.2, 4.8, 5.0, 5.1, 4.9, 5.0]

        result = framework.early_stopping(
            data, data, num_looks=3, current_look=3
        )

        assert result["should_stop"] is False
        assert result["verdict"] == "inconclusive"

    def test_early_stopping_spending_monotonic(self, framework: ABTestFramework) -> None:
        """Alpha spending should increase with information fraction."""
        control = [5.0, 5.1, 4.9, 5.0, 5.2]
        treatment = [5.5, 5.6, 5.4, 5.5, 5.7]

        alphas = []
        for look in range(1, 6):
            result = framework.early_stopping(
                control, treatment, num_looks=5, current_look=look
            )
            alphas.append(result["adjusted_alpha"])

        # Each alpha should be >= previous (monotonically non-decreasing)
        for i in range(1, len(alphas)):
            assert alphas[i] >= alphas[i - 1]

    def test_integration_with_statistical_analyzer(
        self, framework_with_analyzer: ABTestFramework
    ) -> None:
        """Framework should work correctly with explicit StatisticalAnalyzer."""
        control = [2.0, 2.5, 3.0, 2.3, 2.7, 2.4, 2.6, 2.2, 2.8, 2.1]
        treatment = [4.0, 4.5, 5.0, 4.3, 4.7, 4.4, 4.6, 4.2, 4.8, 4.1]

        result = framework_with_analyzer.run_test(control, treatment)

        assert result["verdict"] == "improved"
        assert result["p_value"] < 0.05
        assert result["effect_size"] > 0

    def test_framework_creates_default_analyzer(self) -> None:
        """Framework creates its own analyzer if none provided."""
        framework = ABTestFramework()
        assert framework.analyzer is not None
        assert isinstance(framework.analyzer, StatisticalAnalyzer)

    def test_run_test_power_estimate_reasonable(self, framework: ABTestFramework) -> None:
        """Power estimate should be between 0 and 1."""
        control = [2.0, 2.5, 3.0, 2.3, 2.7, 2.4, 2.6, 2.2, 2.8, 2.1]
        treatment = [4.0, 4.5, 5.0, 4.3, 4.7, 4.4, 4.6, 4.2, 4.8, 4.1]

        result = framework.run_test(control, treatment)

        assert 0.0 <= result["power_estimate"] <= 1.0
        # With this clear difference, power should be high
        assert result["power_estimate"] > 0.5
