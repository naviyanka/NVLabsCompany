"""A/B Test Framework - experiment design, execution, and early stopping.

Provides tools for designing A/B tests (sample size calculation),
running tests (with p-value, CI, effect size, and verdict), and
implementing early stopping via O'Brien-Fleming alpha spending.
Uses only Python stdlib (math, statistics).
"""

import math
import statistics
from typing import Any

from nexus.evolution.statistical import StatisticalAnalyzer


class ABTestFramework:
    """Framework for designing and running A/B tests.

    Supports sample size calculation, test execution with comprehensive
    result analysis, and interim analysis with early stopping using
    O'Brien-Fleming alpha spending boundaries.
    """

    def __init__(self, statistical_analyzer: StatisticalAnalyzer | None = None) -> None:
        """Initialize the A/B test framework.

        Args:
            statistical_analyzer: Optional StatisticalAnalyzer instance.
                If None, a new instance is created internally.
        """
        self.analyzer = statistical_analyzer or StatisticalAnalyzer()

    def design_test(
        self,
        baseline_mean: float,
        baseline_std: float,
        min_detectable_effect: float,
        alpha: float = 0.05,
        power: float = 0.8,
    ) -> dict[str, Any]:
        """Calculate required sample size for an A/B test.

        Uses the standard formula for two-sample t-test sample size
        calculation based on desired power and significance level.

        Args:
            baseline_mean: Expected mean of the control group.
            baseline_std: Expected standard deviation of the control group.
            min_detectable_effect: Minimum effect size to detect (absolute).
            alpha: Significance level (default 0.05).
            power: Statistical power (default 0.8).

        Returns:
            Dict with keys: sample_size_per_group, total_sample_size,
            alpha, power, min_detectable_effect, baseline_mean, baseline_std.
        """
        if baseline_std <= 0 or min_detectable_effect <= 0:
            return {
                "sample_size_per_group": 0,
                "total_sample_size": 0,
                "alpha": alpha,
                "power": power,
                "min_detectable_effect": min_detectable_effect,
                "baseline_mean": baseline_mean,
                "baseline_std": baseline_std,
            }

        # Z-scores for alpha/2 (two-tailed) and power
        z_alpha = self.analyzer._z_score_for_confidence(1.0 - alpha)
        z_beta = self.analyzer._z_score_for_confidence(power + (1.0 - power) / 2.0)

        # Sample size formula: n = 2 * (z_alpha + z_beta)^2 * sigma^2 / delta^2
        n_per_group = math.ceil(
            2.0 * (z_alpha + z_beta) ** 2 * baseline_std ** 2 / min_detectable_effect ** 2
        )

        # Ensure at least 2 per group
        n_per_group = max(n_per_group, 2)

        return {
            "sample_size_per_group": n_per_group,
            "total_sample_size": n_per_group * 2,
            "alpha": alpha,
            "power": power,
            "min_detectable_effect": min_detectable_effect,
            "baseline_mean": baseline_mean,
            "baseline_std": baseline_std,
        }

    def run_test(
        self,
        control_results: list[float],
        treatment_results: list[float],
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        """Run an A/B test and return comprehensive results.

        Computes p-value, confidence interval of the difference, effect
        size (Cohen's d), estimated power, and a verdict.

        Args:
            control_results: Observations from the control group.
            treatment_results: Observations from the treatment group.
            alpha: Significance level (default 0.05).

        Returns:
            Dict with keys: p_value, confidence_interval, effect_size,
            cohens_d, power_estimate, verdict ('improved', 'degraded',
            or 'inconclusive'), control_mean, treatment_mean,
            mean_difference.
        """
        n1 = len(control_results)
        n2 = len(treatment_results)

        if n1 < 2 or n2 < 2:
            return {
                "p_value": 1.0,
                "confidence_interval": {"lower": 0.0, "upper": 0.0},
                "effect_size": 0.0,
                "cohens_d": 0.0,
                "power_estimate": 0.0,
                "verdict": "inconclusive",
                "control_mean": statistics.mean(control_results) if control_results else 0.0,
                "treatment_mean": statistics.mean(treatment_results) if treatment_results else 0.0,
                "mean_difference": 0.0,
            }

        # Run significance test
        sig_result = self.analyzer.compute_significance(
            control_results, treatment_results, alpha=alpha
        )

        mean1 = statistics.mean(control_results)
        mean2 = statistics.mean(treatment_results)
        var1 = statistics.variance(control_results)
        var2 = statistics.variance(treatment_results)
        mean_diff = mean2 - mean1

        # Confidence interval of the difference
        se_diff = math.sqrt(var1 / n1 + var2 / n2)
        z = self.analyzer._z_score_for_confidence(1.0 - alpha)
        ci_lower = mean_diff - z * se_diff
        ci_upper = mean_diff + z * se_diff

        # Cohen's d
        pooled_std = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))
        if pooled_std > 0:
            cohens_d = mean_diff / pooled_std
        else:
            cohens_d = 0.0

        # Estimate power (post-hoc)
        power_estimate = self._estimate_power(
            n1, n2, mean_diff, math.sqrt((var1 + var2) / 2.0), alpha
        )

        # Determine verdict
        if sig_result["is_significant"]:
            if mean_diff > 0:
                verdict = "improved"
            else:
                verdict = "degraded"
        else:
            verdict = "inconclusive"

        return {
            "p_value": sig_result["p_value"],
            "confidence_interval": {"lower": ci_lower, "upper": ci_upper},
            "effect_size": abs(cohens_d),
            "cohens_d": cohens_d,
            "power_estimate": power_estimate,
            "verdict": verdict,
            "control_mean": mean1,
            "treatment_mean": mean2,
            "mean_difference": mean_diff,
        }

    def early_stopping(
        self,
        control_results: list[float],
        treatment_results: list[float],
        num_looks: int,
        current_look: int,
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        """Perform interim analysis with O'Brien-Fleming alpha spending.

        The O'Brien-Fleming spending function allocates very little alpha
        to early looks and more to later looks, making early stopping
        conservative (requires very strong evidence early on).

        Args:
            control_results: Current control observations.
            treatment_results: Current treatment observations.
            num_looks: Total planned number of interim analyses.
            current_look: Current look number (1-indexed).
            alpha: Overall significance level (default 0.05).

        Returns:
            Dict with keys: should_stop, adjusted_alpha, p_value,
            information_fraction, current_look, num_looks, spending,
            verdict.
        """
        if num_looks < 1:
            num_looks = 1
        if current_look < 1:
            current_look = 1
        if current_look > num_looks:
            current_look = num_looks

        # Information fraction
        info_fraction = current_look / num_looks

        # O'Brien-Fleming spending function
        # alpha_spent(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))
        # where t is the information fraction
        adjusted_alpha = self._obrien_fleming_spending(alpha, info_fraction)

        # Run significance test with adjusted alpha
        sig_result = self.analyzer.compute_significance(
            control_results, treatment_results, alpha=adjusted_alpha
        )

        should_stop = sig_result["is_significant"]

        # Determine verdict
        if should_stop:
            mean1 = statistics.mean(control_results) if len(control_results) >= 1 else 0.0
            mean2 = statistics.mean(treatment_results) if len(treatment_results) >= 1 else 0.0
            if mean2 > mean1:
                verdict = "improved"
            else:
                verdict = "degraded"
        else:
            verdict = "continue" if current_look < num_looks else "inconclusive"

        return {
            "should_stop": should_stop,
            "adjusted_alpha": adjusted_alpha,
            "p_value": sig_result["p_value"],
            "information_fraction": info_fraction,
            "current_look": current_look,
            "num_looks": num_looks,
            "spending": adjusted_alpha,
            "verdict": verdict,
        }

    def _obrien_fleming_spending(self, alpha: float, info_fraction: float) -> float:
        """Calculate O'Brien-Fleming alpha spending at given information fraction.

        Implements the spending function:
        alpha_spent(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))

        where Phi is the standard normal CDF and t is the information fraction.

        Args:
            alpha: Overall significance level.
            info_fraction: Information fraction (0 < t <= 1).

        Returns:
            The adjusted alpha level for this interim look.
        """
        if info_fraction <= 0:
            return 0.0
        if info_fraction >= 1.0:
            return alpha

        # z_{alpha/2}
        z_crit = self.analyzer._z_score_for_confidence(1.0 - alpha)

        # O'Brien-Fleming boundary: z_crit / sqrt(info_fraction)
        z_boundary = z_crit / math.sqrt(info_fraction)

        # Convert back to alpha: 2 * (1 - Phi(z_boundary))
        # Using the complementary error function relationship:
        # Phi(z) = 0.5 * (1 + erf(z/sqrt(2)))
        # 1 - Phi(z) = 0.5 * erfc(z/sqrt(2))
        adjusted = 2.0 * 0.5 * math.erfc(z_boundary / math.sqrt(2.0))

        return adjusted

    def _estimate_power(
        self,
        n1: int,
        n2: int,
        effect: float,
        sigma: float,
        alpha: float,
    ) -> float:
        """Estimate statistical power for the observed effect.

        Args:
            n1: Control sample size.
            n2: Treatment sample size.
            effect: Observed effect (mean difference).
            sigma: Estimated pooled standard deviation.
            alpha: Significance level.

        Returns:
            Estimated power (probability of detecting the effect).
        """
        if sigma <= 0 or n1 < 2 or n2 < 2:
            return 0.0

        # Standard error
        se = sigma * math.sqrt(1.0 / n1 + 1.0 / n2)
        if se <= 0:
            return 0.0

        # Critical z-value
        z_crit = self.analyzer._z_score_for_confidence(1.0 - alpha)

        # Non-centrality parameter
        ncp = abs(effect) / se

        # Power = P(Z > z_crit - ncp) for one side
        # For two-tailed: power ~ Phi(ncp - z_crit) + Phi(-ncp - z_crit)
        # The second term is negligible for reasonable effect sizes
        z_power = ncp - z_crit
        # Approximate Phi(z_power) using erfc
        power = 0.5 * (1.0 + math.erf(z_power / math.sqrt(2.0)))

        return max(0.0, min(1.0, power))
