"""Statistical Analyzer - pure statistics using Python stdlib only.

Provides significance testing, trend detection, confidence intervals,
and effect size calculations for the Evolution Engine. Uses only the
math and statistics stdlib modules (no numpy/scipy).
"""

import math
import statistics
from typing import Any


class StatisticalAnalyzer:
    """Performs statistical analysis for evolution metrics.

    All methods use only Python's math and statistics stdlib modules.
    Results are returned as dicts with documented keys for transparency.
    """

    def compute_significance(
        self,
        control: list[float],
        treatment: list[float],
        alpha: float = 0.05,
    ) -> dict[str, Any]:
        """Compute statistical significance using Welch's t-test.

        Performs a two-sample t-test (Welch's) without assuming equal variances.

        Args:
            control: Sample data from the control group.
            treatment: Sample data from the treatment group.
            alpha: Significance level (default 0.05).

        Returns:
            Dict with keys: t_statistic, p_value, degrees_of_freedom,
            is_significant, alpha.
        """
        n1 = len(control)
        n2 = len(treatment)

        if n1 < 2 or n2 < 2:
            return {
                "t_statistic": 0.0,
                "p_value": 1.0,
                "degrees_of_freedom": 0.0,
                "is_significant": False,
                "alpha": alpha,
            }

        mean1 = statistics.mean(control)
        mean2 = statistics.mean(treatment)
        var1 = statistics.variance(control)
        var2 = statistics.variance(treatment)

        # Welch's t-statistic
        se = math.sqrt(var1 / n1 + var2 / n2)
        if se == 0:
            return {
                "t_statistic": 0.0,
                "p_value": 1.0,
                "degrees_of_freedom": float(n1 + n2 - 2),
                "is_significant": False,
                "alpha": alpha,
            }

        t_stat = (mean2 - mean1) / se

        # Welch-Satterthwaite degrees of freedom
        num = (var1 / n1 + var2 / n2) ** 2
        denom = ((var1 / n1) ** 2 / (n1 - 1)) + ((var2 / n2) ** 2 / (n2 - 1))
        if denom == 0:
            df = float(n1 + n2 - 2)
        else:
            df = num / denom

        # Approximate p-value using the t-distribution CDF
        p_value = self._t_distribution_two_tailed_p(t_stat, df)

        return {
            "t_statistic": t_stat,
            "p_value": p_value,
            "degrees_of_freedom": df,
            "is_significant": p_value < alpha,
            "alpha": alpha,
        }

    def detect_trend(self, values: list[float]) -> dict[str, Any]:
        """Detect trend in a time series using linear regression.

        Fits a simple linear regression (y = slope*x + intercept) to the
        values indexed by position.

        Args:
            values: Ordered sequence of metric values.

        Returns:
            Dict with keys: slope, intercept, r_squared, direction
            (one of 'upward', 'downward', 'flat').
        """
        n = len(values)
        if n < 2:
            return {
                "slope": 0.0,
                "intercept": values[0] if values else 0.0,
                "r_squared": 0.0,
                "direction": "flat",
            }

        x = list(range(n))
        mean_x = sum(x) / n
        mean_y = sum(values) / n

        # Compute slope and intercept
        ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, values))
        ss_xx = sum((xi - mean_x) ** 2 for xi in x)
        ss_yy = sum((yi - mean_y) ** 2 for yi in values)

        if ss_xx == 0:
            slope = 0.0
        else:
            slope = ss_xy / ss_xx

        intercept = mean_y - slope * mean_x

        # R-squared
        if ss_yy == 0:
            r_squared = 1.0 if ss_xy == 0 else 0.0
        else:
            r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_xx != 0 else 0.0

        # Determine direction using a threshold relative to data scale
        # Use coefficient of variation of slope relative to mean
        if n > 1 and ss_xx > 0:
            # Slope significance: compare slope magnitude to data spread
            data_range = max(values) - min(values) if max(values) != min(values) else 1.0
            normalized_slope = abs(slope * (n - 1)) / data_range if data_range != 0 else 0.0
            if normalized_slope < 0.1:
                direction = "flat"
            elif slope > 0:
                direction = "upward"
            else:
                direction = "downward"
        else:
            direction = "flat"

        return {
            "slope": slope,
            "intercept": intercept,
            "r_squared": r_squared,
            "direction": direction,
        }

    def compute_confidence_interval(
        self,
        data: list[float],
        confidence: float = 0.95,
    ) -> dict[str, Any]:
        """Compute confidence interval using normal approximation.

        Args:
            data: Sample data.
            confidence: Confidence level (default 0.95).

        Returns:
            Dict with keys: mean, lower, upper, confidence, std_error,
            sample_size.
        """
        n = len(data)
        if n < 2:
            mean_val = data[0] if data else 0.0
            return {
                "mean": mean_val,
                "lower": mean_val,
                "upper": mean_val,
                "confidence": confidence,
                "std_error": 0.0,
                "sample_size": n,
            }

        mean_val = statistics.mean(data)
        std_dev = statistics.stdev(data)
        std_error = std_dev / math.sqrt(n)

        # Z-score for given confidence level (normal approximation)
        z = self._z_score_for_confidence(confidence)

        margin = z * std_error

        return {
            "mean": mean_val,
            "lower": mean_val - margin,
            "upper": mean_val + margin,
            "confidence": confidence,
            "std_error": std_error,
            "sample_size": n,
        }

    def is_significant_improvement(
        self,
        control: list[float],
        treatment: list[float],
        min_effect_size: float = 0.2,
    ) -> dict[str, Any]:
        """Determine if treatment is a significant improvement over control.

        Combines statistical significance (Welch's t-test) with practical
        significance (Cohen's d effect size).

        Args:
            control: Control group data.
            treatment: Treatment group data.
            min_effect_size: Minimum Cohen's d for practical significance
                (0.2=small, 0.5=medium, 0.8=large).

        Returns:
            Dict with keys: is_significant, is_practically_significant,
            is_improvement, cohens_d, p_value, effect_interpretation.
        """
        sig_result = self.compute_significance(control, treatment)

        # Compute Cohen's d
        n1 = len(control)
        n2 = len(treatment)

        if n1 < 2 or n2 < 2:
            return {
                "is_significant": False,
                "is_practically_significant": False,
                "is_improvement": False,
                "cohens_d": 0.0,
                "p_value": 1.0,
                "effect_interpretation": "insufficient_data",
            }

        mean1 = statistics.mean(control)
        mean2 = statistics.mean(treatment)
        var1 = statistics.variance(control)
        var2 = statistics.variance(treatment)

        # Pooled standard deviation for Cohen's d
        pooled_std = math.sqrt(((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2))

        if pooled_std == 0:
            cohens_d = 0.0
        else:
            cohens_d = (mean2 - mean1) / pooled_std

        # Interpret effect size
        abs_d = abs(cohens_d)
        if abs_d < 0.2:
            effect_interpretation = "negligible"
        elif abs_d < 0.5:
            effect_interpretation = "small"
        elif abs_d < 0.8:
            effect_interpretation = "medium"
        else:
            effect_interpretation = "large"

        is_practically_significant = abs_d >= min_effect_size
        is_improvement = mean2 > mean1

        return {
            "is_significant": sig_result["is_significant"],
            "is_practically_significant": is_practically_significant,
            "is_improvement": is_improvement and sig_result["is_significant"] and is_practically_significant,
            "cohens_d": cohens_d,
            "p_value": sig_result["p_value"],
            "effect_interpretation": effect_interpretation,
        }

    def _z_score_for_confidence(self, confidence: float) -> float:
        """Approximate z-score for a given confidence level.

        Uses the rational approximation for the inverse normal CDF
        (Abramowitz and Stegun approximation 26.2.23).

        Args:
            confidence: Confidence level (e.g. 0.95).

        Returns:
            The z-score corresponding to the confidence level.
        """
        # For two-tailed: alpha/2 in each tail
        p = (1.0 + confidence) / 2.0

        # Rational approximation of the inverse normal CDF (probit)
        # for 0.5 < p < 1.0
        t = math.sqrt(-2.0 * math.log(1.0 - p))

        # Coefficients for rational approximation
        c0 = 2.515517
        c1 = 0.802853
        c2 = 0.010328
        d1 = 1.432788
        d2 = 0.189269
        d3 = 0.001308

        z = t - (c0 + c1 * t + c2 * t * t) / (1.0 + d1 * t + d2 * t * t + d3 * t * t * t)
        return z

    def _t_distribution_two_tailed_p(self, t_stat: float, df: float) -> float:
        """Approximate two-tailed p-value from a t-distribution.

        Uses the regularized incomplete beta function approximation.

        Args:
            t_stat: The t-statistic.
            df: Degrees of freedom.

        Returns:
            Approximate two-tailed p-value.
        """
        if df <= 0:
            return 1.0

        # Use the relationship between t-distribution and incomplete beta
        x = df / (df + t_stat * t_stat)
        # p = I_x(df/2, 1/2) for two-tailed
        p = self._regularized_incomplete_beta(x, df / 2.0, 0.5)
        return p

    def _regularized_incomplete_beta(self, x: float, a: float, b: float) -> float:
        """Compute the regularized incomplete beta function I_x(a, b).

        Uses a continued fraction expansion for numerical stability.

        Args:
            x: Upper limit of integration (0 <= x <= 1).
            a: First shape parameter.
            b: Second shape parameter.

        Returns:
            The regularized incomplete beta function value.
        """
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0

        # Use symmetry relation if needed for better convergence
        if x > (a + 1.0) / (a + b + 2.0):
            return 1.0 - self._regularized_incomplete_beta(1.0 - x, b, a)

        # Compute log of the beta function prefix
        ln_prefix = (
            a * math.log(x)
            + b * math.log(1.0 - x)
            - math.log(a)
            - self._log_beta(a, b)
        )

        # Continued fraction (Lentz's method)
        front = math.exp(ln_prefix)
        cf = self._beta_continued_fraction(x, a, b)

        return front * cf

    def _beta_continued_fraction(self, x: float, a: float, b: float) -> float:
        """Evaluate the continued fraction for the incomplete beta function.

        Args:
            x: The x value.
            a: First shape parameter.
            b: Second shape parameter.

        Returns:
            Continued fraction value.
        """
        max_iter = 200
        eps = 1.0e-10
        tiny = 1.0e-30

        # Modified Lentz's method
        f = 1.0
        c = 1.0
        d = 1.0 - (a + b) * x / (a + 1.0)
        if abs(d) < tiny:
            d = tiny
        d = 1.0 / d
        f = d

        for m in range(1, max_iter + 1):
            # Even step
            m2 = 2 * m
            numerator = m * (b - m) * x / ((a + m2 - 1.0) * (a + m2))
            d = 1.0 + numerator * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + numerator / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            f *= c * d

            # Odd step
            numerator = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1.0))
            d = 1.0 + numerator * d
            if abs(d) < tiny:
                d = tiny
            c = 1.0 + numerator / c
            if abs(c) < tiny:
                c = tiny
            d = 1.0 / d
            delta = c * d
            f *= delta

            if abs(delta - 1.0) < eps:
                break

        return f

    def _log_beta(self, a: float, b: float) -> float:
        """Compute log of the Beta function B(a, b) = Gamma(a)*Gamma(b)/Gamma(a+b).

        Args:
            a: First parameter.
            b: Second parameter.

        Returns:
            log(B(a, b)).
        """
        return math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
