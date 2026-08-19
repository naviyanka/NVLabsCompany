"""Tests for the Model Evaluation Framework.

Validates all evaluation components: benchmark definitions, metric
calculations, model evaluator, and report generation/export.
Tests use deterministic inputs and mock adapter functions.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from nexus.evaluation.benchmark import Benchmark, BenchmarkSuite, TestCase
from nexus.evaluation.evaluator import EvaluationConfig, EvaluationResult, ModelEvaluator
from nexus.evaluation.metrics import accuracy, cost_total, latency_stats, token_efficiency
from nexus.evaluation.reporter import (
    EvaluationReport,
    ReportFormat,
    compare_results,
    export_report,
    generate_report,
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def sample_test_cases() -> list[TestCase]:
    """Create sample test cases for benchmark tests."""
    return [
        TestCase(
            input="What is 2+2?",
            expected_output="4",
            metadata={"difficulty": "easy"},
            tags=["math", "arithmetic"],
        ),
        TestCase(
            input="What is the capital of France?",
            expected_output="Paris",
            metadata={"difficulty": "easy"},
            tags=["geography", "facts"],
        ),
        TestCase(
            input="What is 10*5?",
            expected_output="50",
            metadata={"difficulty": "easy"},
            tags=["math", "arithmetic"],
        ),
    ]


@pytest.fixture
def sample_benchmark(sample_test_cases: list[TestCase]) -> Benchmark:
    """Create a sample benchmark with test cases."""
    return Benchmark(
        name="basic-qa",
        description="Basic question-answering benchmark",
        test_cases=sample_test_cases,
        created_at="2024-01-15T10:00:00+00:00",
    )


@pytest.fixture
def sample_config() -> EvaluationConfig:
    """Create a sample evaluation config."""
    return EvaluationConfig(
        model_name="test-model-v1",
        prompt_template="Answer: {input}",
        temperature=0.0,
        max_tokens=256,
        num_runs=1,
    )


@pytest.fixture
def mock_adapter_fn() -> AsyncMock:
    """Create a mock adapter function that returns deterministic outputs."""
    adapter = AsyncMock()
    # Return correct answers for our test cases
    adapter.side_effect = ["4", "Paris", "50"]
    return adapter


@pytest.fixture
def sample_evaluation_result(sample_config: EvaluationConfig) -> EvaluationResult:
    """Create a sample evaluation result."""
    return EvaluationResult(
        config=sample_config,
        predictions=["4", "Paris", "50"],
        metrics={
            "accuracy": 1.0,
            "latency": {"mean": 0.1, "p50": 0.09, "p95": 0.15, "p99": 0.18, "max": 0.2},
            "cost": {"total_input_tokens": 100, "total_output_tokens": 30, "estimated_cost": 0.00021},
            "token_efficiency": 2.5,
            "total_test_cases": 3,
        },
        duration=0.5,
        timestamp="2024-01-15T10:05:00+00:00",
    )


# ============================================================
# TestCase Tests
# ============================================================


class TestTestCase:
    """Tests for the TestCase dataclass."""

    def test_creation_with_all_fields(self):
        """TestCase can be created with all fields specified."""
        tc = TestCase(
            input="What is 1+1?",
            expected_output="2",
            metadata={"source": "math-set"},
            tags=["math"],
        )
        assert tc.input == "What is 1+1?"
        assert tc.expected_output == "2"
        assert tc.metadata == {"source": "math-set"}
        assert tc.tags == ["math"]

    def test_creation_with_defaults(self):
        """TestCase uses empty defaults for metadata and tags."""
        tc = TestCase(input="hello", expected_output="hi")
        assert tc.metadata == {}
        assert tc.tags == []

    def test_to_dict(self):
        """TestCase serializes to a correct dictionary."""
        tc = TestCase(
            input="test input",
            expected_output="test output",
            metadata={"key": "value"},
            tags=["tag1", "tag2"],
        )
        result = tc.to_dict()
        assert result == {
            "input": "test input",
            "expected_output": "test output",
            "metadata": {"key": "value"},
            "tags": ["tag1", "tag2"],
        }

    def test_from_dict(self):
        """TestCase can be deserialized from a dictionary."""
        data = {
            "input": "question",
            "expected_output": "answer",
            "metadata": {"difficulty": "hard"},
            "tags": ["trivia"],
        }
        tc = TestCase.from_dict(data)
        assert tc.input == "question"
        assert tc.expected_output == "answer"
        assert tc.metadata == {"difficulty": "hard"}
        assert tc.tags == ["trivia"]

    def test_from_dict_with_missing_optional_fields(self):
        """TestCase from_dict handles missing optional fields."""
        data = {"input": "q", "expected_output": "a"}
        tc = TestCase.from_dict(data)
        assert tc.metadata == {}
        assert tc.tags == []

    def test_roundtrip_serialization(self):
        """TestCase survives a to_dict/from_dict roundtrip."""
        original = TestCase(
            input="input text",
            expected_output="output text",
            metadata={"nested": {"key": 42}},
            tags=["a", "b", "c"],
        )
        restored = TestCase.from_dict(original.to_dict())
        assert restored.input == original.input
        assert restored.expected_output == original.expected_output
        assert restored.metadata == original.metadata
        assert restored.tags == original.tags


# ============================================================
# Benchmark Tests
# ============================================================


class TestBenchmark:
    """Tests for the Benchmark dataclass."""

    def test_creation(self, sample_test_cases: list[TestCase]):
        """Benchmark can be created with all fields."""
        bm = Benchmark(
            name="test-bench",
            description="A test benchmark",
            test_cases=sample_test_cases,
        )
        assert bm.name == "test-bench"
        assert bm.description == "A test benchmark"
        assert len(bm.test_cases) == 3

    def test_creation_with_defaults(self):
        """Benchmark uses empty defaults for test_cases."""
        bm = Benchmark(name="empty", description="Empty benchmark")
        assert bm.test_cases == []
        assert bm.created_at is not None

    def test_add_test_case(self):
        """add_test_case appends to test_cases list."""
        bm = Benchmark(name="bench", description="desc")
        tc = TestCase(input="q", expected_output="a")
        bm.add_test_case(tc)
        assert len(bm.test_cases) == 1
        assert bm.test_cases[0] is tc

    def test_filter_by_tags(self, sample_benchmark: Benchmark):
        """filter_by_tags returns test cases matching any specified tag."""
        math_cases = sample_benchmark.filter_by_tags(["math"])
        assert len(math_cases) == 2
        geo_cases = sample_benchmark.filter_by_tags(["geography"])
        assert len(geo_cases) == 1

    def test_filter_by_tags_no_match(self, sample_benchmark: Benchmark):
        """filter_by_tags returns empty list when no tags match."""
        result = sample_benchmark.filter_by_tags(["nonexistent"])
        assert result == []

    def test_filter_by_multiple_tags(self, sample_benchmark: Benchmark):
        """filter_by_tags with multiple tags returns union of matches."""
        result = sample_benchmark.filter_by_tags(["math", "geography"])
        assert len(result) == 3  # All test cases match

    def test_to_dict(self, sample_benchmark: Benchmark):
        """Benchmark serializes to a correct dictionary."""
        result = sample_benchmark.to_dict()
        assert result["name"] == "basic-qa"
        assert result["description"] == "Basic question-answering benchmark"
        assert len(result["test_cases"]) == 3
        assert result["created_at"] == "2024-01-15T10:00:00+00:00"

    def test_from_dict(self):
        """Benchmark can be deserialized from a dictionary."""
        data = {
            "name": "restored",
            "description": "A restored benchmark",
            "test_cases": [
                {"input": "q1", "expected_output": "a1", "metadata": {}, "tags": ["t1"]},
            ],
            "created_at": "2024-01-01T00:00:00+00:00",
        }
        bm = Benchmark.from_dict(data)
        assert bm.name == "restored"
        assert len(bm.test_cases) == 1
        assert bm.test_cases[0].tags == ["t1"]

    def test_roundtrip_serialization(self, sample_benchmark: Benchmark):
        """Benchmark survives a to_dict/from_dict roundtrip."""
        restored = Benchmark.from_dict(sample_benchmark.to_dict())
        assert restored.name == sample_benchmark.name
        assert len(restored.test_cases) == len(sample_benchmark.test_cases)


# ============================================================
# BenchmarkSuite Tests
# ============================================================


class TestBenchmarkSuite:
    """Tests for the BenchmarkSuite dataclass."""

    def test_creation(self, sample_benchmark: Benchmark):
        """BenchmarkSuite can be created with benchmarks."""
        suite = BenchmarkSuite(
            name="full-suite",
            description="Full test suite",
            benchmarks=[sample_benchmark],
        )
        assert suite.name == "full-suite"
        assert len(suite.benchmarks) == 1

    def test_add_benchmark(self, sample_benchmark: Benchmark):
        """add_benchmark appends to the benchmarks list."""
        suite = BenchmarkSuite(name="suite", description="desc")
        suite.add_benchmark(sample_benchmark)
        assert len(suite.benchmarks) == 1

    def test_get_all_test_cases(self, sample_benchmark: Benchmark):
        """get_all_test_cases returns flattened test cases from all benchmarks."""
        bm2 = Benchmark(
            name="extra",
            description="Extra benchmark",
            test_cases=[TestCase(input="x", expected_output="y")],
        )
        suite = BenchmarkSuite(
            name="suite",
            description="desc",
            benchmarks=[sample_benchmark, bm2],
        )
        all_cases = suite.get_all_test_cases()
        assert len(all_cases) == 4  # 3 from sample + 1 from extra

    def test_filter_by_tags(self, sample_benchmark: Benchmark):
        """filter_by_tags filters across all benchmarks."""
        suite = BenchmarkSuite(
            name="suite",
            description="desc",
            benchmarks=[sample_benchmark],
        )
        math_cases = suite.filter_by_tags(["math"])
        assert len(math_cases) == 2

    def test_to_dict(self, sample_benchmark: Benchmark):
        """BenchmarkSuite serializes to a correct dictionary."""
        suite = BenchmarkSuite(
            name="suite",
            description="desc",
            benchmarks=[sample_benchmark],
        )
        result = suite.to_dict()
        assert result["name"] == "suite"
        assert len(result["benchmarks"]) == 1

    def test_from_dict(self):
        """BenchmarkSuite can be deserialized from a dictionary."""
        data = {
            "name": "restored-suite",
            "description": "Restored suite",
            "benchmarks": [
                {
                    "name": "bench1",
                    "description": "First",
                    "test_cases": [],
                    "created_at": "2024-01-01T00:00:00+00:00",
                }
            ],
        }
        suite = BenchmarkSuite.from_dict(data)
        assert suite.name == "restored-suite"
        assert len(suite.benchmarks) == 1

    def test_roundtrip_serialization(self, sample_benchmark: Benchmark):
        """BenchmarkSuite survives a to_dict/from_dict roundtrip."""
        suite = BenchmarkSuite(
            name="roundtrip",
            description="Roundtrip test",
            benchmarks=[sample_benchmark],
        )
        restored = BenchmarkSuite.from_dict(suite.to_dict())
        assert restored.name == suite.name
        assert len(restored.benchmarks) == len(suite.benchmarks)


# ============================================================
# Metrics Tests
# ============================================================


class TestAccuracy:
    """Tests for the accuracy metric function."""

    def test_perfect_accuracy(self):
        """Returns 1.0 when all predictions match expected."""
        preds = ["a", "b", "c"]
        expected = ["a", "b", "c"]
        assert accuracy(preds, expected) == 1.0

    def test_zero_accuracy(self):
        """Returns 0.0 when no predictions match expected."""
        preds = ["x", "y", "z"]
        expected = ["a", "b", "c"]
        assert accuracy(preds, expected) == 0.0

    def test_partial_accuracy(self):
        """Returns correct ratio for partial matches."""
        preds = ["a", "wrong", "c"]
        expected = ["a", "b", "c"]
        assert accuracy(preds, expected) == pytest.approx(2 / 3)

    def test_empty_lists(self):
        """Returns 0.0 for empty input lists."""
        assert accuracy([], []) == 0.0

    def test_mismatched_lengths_raises(self):
        """Raises ValueError when lists have different lengths."""
        with pytest.raises(ValueError, match="same length"):
            accuracy(["a", "b"], ["a"])

    def test_case_sensitive(self):
        """Accuracy is case-sensitive."""
        preds = ["Paris", "london"]
        expected = ["Paris", "London"]
        assert accuracy(preds, expected) == 0.5

    def test_single_element(self):
        """Works correctly with single-element lists."""
        assert accuracy(["yes"], ["yes"]) == 1.0
        assert accuracy(["yes"], ["no"]) == 0.0


class TestLatencyStats:
    """Tests for the latency_stats metric function."""

    def test_basic_stats(self):
        """Computes correct statistics for a known set of values."""
        latencies = [0.1, 0.2, 0.3, 0.4, 0.5]
        stats = latency_stats(latencies)
        assert stats["mean"] == pytest.approx(0.3)
        assert stats["p50"] == pytest.approx(0.3)
        assert stats["max"] == pytest.approx(0.5)

    def test_single_value(self):
        """Works correctly with a single latency value."""
        stats = latency_stats([0.5])
        assert stats["mean"] == pytest.approx(0.5)
        assert stats["p50"] == pytest.approx(0.5)
        assert stats["p95"] == pytest.approx(0.5)
        assert stats["p99"] == pytest.approx(0.5)
        assert stats["max"] == pytest.approx(0.5)

    def test_empty_list(self):
        """Returns all zeros for an empty list."""
        stats = latency_stats([])
        assert stats == {"mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    def test_identical_values(self):
        """Handles identical values correctly."""
        stats = latency_stats([1.0, 1.0, 1.0])
        assert stats["mean"] == pytest.approx(1.0)
        assert stats["p50"] == pytest.approx(1.0)
        assert stats["max"] == pytest.approx(1.0)

    def test_p95_p99_with_many_values(self):
        """P95 and P99 are higher than p50 for varied latencies."""
        # Create a range of latencies with some high outliers
        latencies = [0.1] * 90 + [0.5] * 5 + [1.0] * 5
        stats = latency_stats(latencies)
        assert stats["p50"] < stats["p95"]
        assert stats["p95"] <= stats["p99"]
        assert stats["p99"] <= stats["max"]

    def test_returns_dict_with_correct_keys(self):
        """Return dict has exactly the expected keys."""
        stats = latency_stats([0.1, 0.2])
        assert set(stats.keys()) == {"mean", "p50", "p95", "p99", "max"}


class TestCostTotal:
    """Tests for the cost_total metric function."""

    def test_basic_cost_calculation(self):
        """Computes correct cost for known token counts."""
        counts = [
            {"input_tokens": 1000, "output_tokens": 500},
            {"input_tokens": 2000, "output_tokens": 1000},
        ]
        result = cost_total(counts)
        assert result["total_input_tokens"] == 3000
        assert result["total_output_tokens"] == 1500
        # Cost: (3000/1000)*0.0015 + (1500/1000)*0.002 = 0.0045 + 0.003 = 0.0075
        assert result["estimated_cost"] == pytest.approx(0.0075)

    def test_empty_list(self):
        """Returns zeros for empty input."""
        result = cost_total([])
        assert result["total_input_tokens"] == 0
        assert result["total_output_tokens"] == 0
        assert result["estimated_cost"] == 0.0

    def test_zero_tokens(self):
        """Handles zero token counts correctly."""
        counts = [{"input_tokens": 0, "output_tokens": 0}]
        result = cost_total(counts)
        assert result["estimated_cost"] == 0.0

    def test_missing_fields_default_to_zero(self):
        """Missing token fields default to zero."""
        counts = [{"input_tokens": 100}, {"output_tokens": 200}]
        result = cost_total(counts)
        assert result["total_input_tokens"] == 100
        assert result["total_output_tokens"] == 200

    def test_returns_dict_with_correct_keys(self):
        """Return dict has exactly the expected keys."""
        result = cost_total([{"input_tokens": 10, "output_tokens": 5}])
        assert set(result.keys()) == {"total_input_tokens", "total_output_tokens", "estimated_cost"}


class TestTokenEfficiency:
    """Tests for the token_efficiency metric function."""

    def test_basic_efficiency(self):
        """Computes correct efficiency for known values."""
        outputs = ["hello", "world"]  # 5 + 5 = 10 chars
        token_counts = [10, 10]  # 20 total tokens
        result = token_efficiency(outputs, token_counts)
        assert result == pytest.approx(0.5)  # 10 chars / 20 tokens

    def test_empty_lists(self):
        """Returns 0.0 for empty lists."""
        assert token_efficiency([], []) == 0.0

    def test_zero_tokens(self):
        """Returns 0.0 when total tokens is zero."""
        result = token_efficiency(["some output"], [0])
        assert result == 0.0

    def test_mismatched_lengths_raises(self):
        """Raises ValueError for mismatched list lengths."""
        with pytest.raises(ValueError, match="same length"):
            token_efficiency(["a", "b"], [10])

    def test_high_efficiency(self):
        """Long outputs with few tokens have high efficiency."""
        outputs = ["a" * 100]  # 100 chars
        token_counts = [10]
        result = token_efficiency(outputs, token_counts)
        assert result == pytest.approx(10.0)

    def test_low_efficiency(self):
        """Short outputs with many tokens have low efficiency."""
        outputs = ["hi"]  # 2 chars
        token_counts = [1000]
        result = token_efficiency(outputs, token_counts)
        assert result == pytest.approx(0.002)


# ============================================================
# EvaluationConfig Tests
# ============================================================


class TestEvaluationConfig:
    """Tests for the EvaluationConfig dataclass."""

    def test_creation_with_all_fields(self):
        """EvaluationConfig can be created with all fields."""
        config = EvaluationConfig(
            model_name="gpt-4",
            prompt_template="Q: {input}\nA:",
            temperature=0.7,
            max_tokens=512,
            num_runs=3,
        )
        assert config.model_name == "gpt-4"
        assert config.prompt_template == "Q: {input}\nA:"
        assert config.temperature == 0.7
        assert config.max_tokens == 512
        assert config.num_runs == 3

    def test_creation_with_defaults(self):
        """EvaluationConfig uses sensible defaults."""
        config = EvaluationConfig(model_name="test")
        assert config.prompt_template == "{input}"
        assert config.temperature == 0.0
        assert config.max_tokens == 1024
        assert config.num_runs == 1


# ============================================================
# EvaluationResult Tests
# ============================================================


class TestEvaluationResult:
    """Tests for the EvaluationResult dataclass."""

    def test_creation(self, sample_config: EvaluationConfig):
        """EvaluationResult can be created with all fields."""
        result = EvaluationResult(
            config=sample_config,
            predictions=["a", "b"],
            metrics={"accuracy": 0.5},
            duration=1.5,
        )
        assert result.config is sample_config
        assert result.predictions == ["a", "b"]
        assert result.metrics["accuracy"] == 0.5
        assert result.duration == 1.5
        assert result.timestamp is not None

    def test_to_dict(self, sample_evaluation_result: EvaluationResult):
        """EvaluationResult serializes to a correct dictionary."""
        result_dict = sample_evaluation_result.to_dict()
        assert result_dict["config"]["model_name"] == "test-model-v1"
        assert result_dict["predictions"] == ["4", "Paris", "50"]
        assert result_dict["metrics"]["accuracy"] == 1.0
        assert result_dict["duration"] == 0.5

    def test_from_dict(self):
        """EvaluationResult can be deserialized from a dictionary."""
        data = {
            "config": {
                "model_name": "restored-model",
                "prompt_template": "{input}",
                "temperature": 0.0,
                "max_tokens": 1024,
                "num_runs": 1,
            },
            "predictions": ["x", "y"],
            "metrics": {"accuracy": 0.5},
            "duration": 2.0,
            "timestamp": "2024-01-15T12:00:00+00:00",
        }
        result = EvaluationResult.from_dict(data)
        assert result.config.model_name == "restored-model"
        assert result.predictions == ["x", "y"]
        assert result.duration == 2.0

    def test_roundtrip_serialization(self, sample_evaluation_result: EvaluationResult):
        """EvaluationResult survives a to_dict/from_dict roundtrip."""
        restored = EvaluationResult.from_dict(sample_evaluation_result.to_dict())
        assert restored.config.model_name == sample_evaluation_result.config.model_name
        assert restored.predictions == sample_evaluation_result.predictions
        assert restored.duration == sample_evaluation_result.duration


# ============================================================
# ModelEvaluator Tests
# ============================================================


class TestModelEvaluator:
    """Tests for the ModelEvaluator class."""

    @pytest.mark.asyncio
    async def test_run_benchmark_basic(
        self,
        sample_benchmark: Benchmark,
        sample_config: EvaluationConfig,
    ):
        """ModelEvaluator runs benchmark and returns EvaluationResult."""
        # Mock adapter returns correct answers
        adapter = AsyncMock(side_effect=["4", "Paris", "50"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(sample_benchmark, sample_config, adapter)

        assert isinstance(result, EvaluationResult)
        assert result.config is sample_config
        assert result.predictions == ["4", "Paris", "50"]
        assert result.metrics["accuracy"] == 1.0
        assert result.duration > 0

    @pytest.mark.asyncio
    async def test_run_benchmark_partial_accuracy(
        self,
        sample_benchmark: Benchmark,
        sample_config: EvaluationConfig,
    ):
        """ModelEvaluator computes correct accuracy for partial matches."""
        # Mock adapter returns some wrong answers
        adapter = AsyncMock(side_effect=["4", "London", "50"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(sample_benchmark, sample_config, adapter)

        assert result.metrics["accuracy"] == pytest.approx(2 / 3)
        assert result.predictions == ["4", "London", "50"]

    @pytest.mark.asyncio
    async def test_run_benchmark_measures_latency(
        self,
        sample_benchmark: Benchmark,
        sample_config: EvaluationConfig,
    ):
        """ModelEvaluator measures wall-clock latency for each test case."""
        adapter = AsyncMock(side_effect=["4", "Paris", "50"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(sample_benchmark, sample_config, adapter)

        latency = result.metrics["latency"]
        assert "mean" in latency
        assert "p50" in latency
        assert "p95" in latency
        assert "p99" in latency
        assert "max" in latency
        assert latency["mean"] >= 0

    @pytest.mark.asyncio
    async def test_run_benchmark_computes_cost(
        self,
        sample_benchmark: Benchmark,
        sample_config: EvaluationConfig,
    ):
        """ModelEvaluator computes cost metrics."""
        adapter = AsyncMock(side_effect=["4", "Paris", "50"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(sample_benchmark, sample_config, adapter)

        cost = result.metrics["cost"]
        assert "total_input_tokens" in cost
        assert "total_output_tokens" in cost
        assert "estimated_cost" in cost
        assert cost["total_input_tokens"] > 0
        assert cost["estimated_cost"] >= 0

    @pytest.mark.asyncio
    async def test_run_benchmark_computes_token_efficiency(
        self,
        sample_benchmark: Benchmark,
        sample_config: EvaluationConfig,
    ):
        """ModelEvaluator computes token efficiency metric."""
        adapter = AsyncMock(side_effect=["4", "Paris", "50"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(sample_benchmark, sample_config, adapter)

        assert "token_efficiency" in result.metrics
        assert result.metrics["token_efficiency"] >= 0

    @pytest.mark.asyncio
    async def test_run_benchmark_uses_prompt_template(
        self,
        sample_benchmark: Benchmark,
    ):
        """ModelEvaluator formats input using the config prompt_template."""
        config = EvaluationConfig(
            model_name="test",
            prompt_template="Please answer: {input}",
        )
        adapter = AsyncMock(side_effect=["4", "Paris", "50"])

        evaluator = ModelEvaluator()
        await evaluator.run_benchmark(sample_benchmark, config, adapter)

        # Verify adapter was called with formatted inputs
        calls = adapter.call_args_list
        assert calls[0].args[0] == "Please answer: What is 2+2?"
        assert calls[1].args[0] == "Please answer: What is the capital of France?"
        assert calls[2].args[0] == "Please answer: What is 10*5?"

    @pytest.mark.asyncio
    async def test_run_benchmark_multiple_runs(self):
        """ModelEvaluator supports num_runs > 1 for averaging latency."""
        benchmark = Benchmark(
            name="single",
            description="Single test",
            test_cases=[TestCase(input="q", expected_output="a")],
        )
        config = EvaluationConfig(model_name="test", num_runs=3)
        # Return the same answer 3 times (3 runs for 1 test case)
        adapter = AsyncMock(side_effect=["a", "a", "a"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(benchmark, config, adapter)

        # Adapter should be called num_runs times per test case
        assert adapter.call_count == 3
        assert result.predictions == ["a"]

    @pytest.mark.asyncio
    async def test_run_benchmark_empty_benchmark(self, sample_config: EvaluationConfig):
        """ModelEvaluator handles empty benchmark gracefully."""
        benchmark = Benchmark(name="empty", description="No test cases")
        adapter = AsyncMock()

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(benchmark, sample_config, adapter)

        assert result.predictions == []
        assert result.metrics["accuracy"] == 0.0
        adapter.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_benchmark_records_total_test_cases(
        self,
        sample_benchmark: Benchmark,
        sample_config: EvaluationConfig,
    ):
        """ModelEvaluator records total_test_cases in metrics."""
        adapter = AsyncMock(side_effect=["4", "Paris", "50"])

        evaluator = ModelEvaluator()
        result = await evaluator.run_benchmark(sample_benchmark, sample_config, adapter)

        assert result.metrics["total_test_cases"] == 3


# ============================================================
# Reporter Tests
# ============================================================


class TestEvaluationReport:
    """Tests for the EvaluationReport dataclass."""

    def test_creation(self, sample_evaluation_result: EvaluationResult):
        """EvaluationReport can be created with results and summary."""
        report = EvaluationReport(
            results=[sample_evaluation_result],
            summary={"total_evaluations": 1},
        )
        assert len(report.results) == 1
        assert report.summary["total_evaluations"] == 1
        assert report.generated_at is not None

    def test_to_dict(self, sample_evaluation_result: EvaluationResult):
        """EvaluationReport serializes to a correct dictionary."""
        report = EvaluationReport(
            results=[sample_evaluation_result],
            summary={"best_accuracy": 1.0},
            generated_at="2024-01-15T12:00:00+00:00",
        )
        result_dict = report.to_dict()
        assert len(result_dict["results"]) == 1
        assert result_dict["summary"]["best_accuracy"] == 1.0
        assert result_dict["generated_at"] == "2024-01-15T12:00:00+00:00"

    def test_from_dict(self):
        """EvaluationReport can be deserialized from a dictionary."""
        data = {
            "results": [
                {
                    "config": {
                        "model_name": "test",
                        "prompt_template": "{input}",
                        "temperature": 0.0,
                        "max_tokens": 1024,
                        "num_runs": 1,
                    },
                    "predictions": ["a"],
                    "metrics": {"accuracy": 1.0},
                    "duration": 0.1,
                    "timestamp": "2024-01-01T00:00:00+00:00",
                }
            ],
            "summary": {"total": 1},
            "generated_at": "2024-01-15T12:00:00+00:00",
        }
        report = EvaluationReport.from_dict(data)
        assert len(report.results) == 1
        assert report.summary["total"] == 1


class TestGenerateReport:
    """Tests for the generate_report function."""

    def test_basic_report_generation(self, sample_evaluation_result: EvaluationResult):
        """generate_report produces a report with summary statistics."""
        report = generate_report([sample_evaluation_result])
        assert isinstance(report, EvaluationReport)
        assert len(report.results) == 1
        assert report.summary["total_evaluations"] == 1
        assert report.summary["best_accuracy"] == 1.0
        assert report.summary["mean_accuracy"] == 1.0

    def test_multiple_results(self, sample_config: EvaluationConfig):
        """generate_report handles multiple results correctly."""
        result1 = EvaluationResult(
            config=sample_config,
            predictions=["a"],
            metrics={
                "accuracy": 1.0,
                "cost": {"estimated_cost": 0.001},
            },
            duration=1.0,
        )
        config2 = EvaluationConfig(model_name="model-b")
        result2 = EvaluationResult(
            config=config2,
            predictions=["b"],
            metrics={
                "accuracy": 0.5,
                "cost": {"estimated_cost": 0.002},
            },
            duration=2.0,
        )
        report = generate_report([result1, result2])
        assert report.summary["total_evaluations"] == 2
        assert report.summary["best_accuracy"] == 1.0
        assert report.summary["worst_accuracy"] == 0.5
        assert report.summary["mean_accuracy"] == pytest.approx(0.75)
        assert report.summary["total_duration"] == pytest.approx(3.0)
        assert len(report.summary["models_evaluated"]) == 2

    def test_empty_results(self):
        """generate_report handles empty results list."""
        report = generate_report([])
        assert report.results == []
        assert report.summary == {}


class TestExportReport:
    """Tests for the export_report function."""

    def test_export_json(self, sample_evaluation_result: EvaluationResult):
        """export_report produces valid JSON string."""
        report = generate_report([sample_evaluation_result])
        exported = export_report(report, ReportFormat.JSON)

        # Should be valid JSON
        parsed = json.loads(exported)
        assert "results" in parsed
        assert "summary" in parsed
        assert "generated_at" in parsed

    def test_export_json_structure(self, sample_evaluation_result: EvaluationResult):
        """export_report JSON contains correct data structure."""
        report = generate_report([sample_evaluation_result])
        exported = export_report(report, ReportFormat.JSON)
        parsed = json.loads(exported)

        assert parsed["summary"]["total_evaluations"] == 1
        assert len(parsed["results"]) == 1
        assert parsed["results"][0]["config"]["model_name"] == "test-model-v1"

    def test_export_is_string(self, sample_evaluation_result: EvaluationResult):
        """export_report returns a string."""
        report = generate_report([sample_evaluation_result])
        exported = export_report(report, ReportFormat.JSON)
        assert isinstance(exported, str)


class TestCompareResults:
    """Tests for the compare_results function."""

    def test_basic_comparison(self):
        """compare_results produces correct deltas."""
        config_a = EvaluationConfig(model_name="model-a")
        config_b = EvaluationConfig(model_name="model-b")

        result_a = EvaluationResult(
            config=config_a,
            predictions=["a"],
            metrics={
                "accuracy": 0.6,
                "latency": {"mean": 0.2, "p50": 0.18, "p95": 0.3, "p99": 0.35, "max": 0.4},
                "cost": {"estimated_cost": 0.01},
                "token_efficiency": 2.0,
            },
            duration=1.0,
        )
        result_b = EvaluationResult(
            config=config_b,
            predictions=["b"],
            metrics={
                "accuracy": 0.8,
                "latency": {"mean": 0.1, "p50": 0.09, "p95": 0.15, "p99": 0.18, "max": 0.2},
                "cost": {"estimated_cost": 0.005},
                "token_efficiency": 3.0,
            },
            duration=0.8,
        )

        comparison = compare_results(result_a, result_b)

        assert comparison["model_a"] == "model-a"
        assert comparison["model_b"] == "model-b"
        assert comparison["deltas"]["accuracy"] == pytest.approx(0.2)
        assert comparison["deltas"]["latency"]["mean"] == pytest.approx(-0.1)
        assert comparison["deltas"]["estimated_cost"] == pytest.approx(-0.005)
        assert comparison["deltas"]["token_efficiency"] == pytest.approx(1.0)
        assert comparison["deltas"]["duration"] == pytest.approx(-0.2)

    def test_comparison_summary_flags(self):
        """compare_results summary correctly identifies improvements."""
        config_a = EvaluationConfig(model_name="baseline")
        config_b = EvaluationConfig(model_name="improved")

        result_a = EvaluationResult(
            config=config_a,
            predictions=[],
            metrics={
                "accuracy": 0.5,
                "latency": {"mean": 0.5, "p50": 0.4, "p95": 0.7, "p99": 0.8, "max": 1.0},
                "cost": {"estimated_cost": 0.01},
                "token_efficiency": 1.0,
            },
            duration=2.0,
        )
        result_b = EvaluationResult(
            config=config_b,
            predictions=[],
            metrics={
                "accuracy": 0.9,
                "latency": {"mean": 0.2, "p50": 0.15, "p95": 0.3, "p99": 0.35, "max": 0.4},
                "cost": {"estimated_cost": 0.005},
                "token_efficiency": 2.0,
            },
            duration=1.0,
        )

        comparison = compare_results(result_a, result_b)

        assert comparison["summary"]["accuracy_improved"] is True
        assert comparison["summary"]["latency_improved"] is True
        assert comparison["summary"]["cost_improved"] is True

    def test_comparison_no_improvement(self):
        """compare_results identifies when model_b is worse."""
        config_a = EvaluationConfig(model_name="good")
        config_b = EvaluationConfig(model_name="worse")

        result_a = EvaluationResult(
            config=config_a,
            predictions=[],
            metrics={
                "accuracy": 0.9,
                "latency": {"mean": 0.1, "p50": 0.1, "p95": 0.1, "p99": 0.1, "max": 0.1},
                "cost": {"estimated_cost": 0.001},
                "token_efficiency": 5.0,
            },
            duration=0.5,
        )
        result_b = EvaluationResult(
            config=config_b,
            predictions=[],
            metrics={
                "accuracy": 0.5,
                "latency": {"mean": 0.5, "p50": 0.5, "p95": 0.5, "p99": 0.5, "max": 0.5},
                "cost": {"estimated_cost": 0.01},
                "token_efficiency": 1.0,
            },
            duration=2.0,
        )

        comparison = compare_results(result_a, result_b)

        assert comparison["summary"]["accuracy_improved"] is False
        assert comparison["summary"]["latency_improved"] is False
        assert comparison["summary"]["cost_improved"] is False


# ============================================================
# ReportFormat Tests
# ============================================================


class TestReportFormat:
    """Tests for the ReportFormat enum."""

    def test_json_format_exists(self):
        """JSON format is defined in ReportFormat."""
        assert ReportFormat.JSON.value == "json"

    def test_enum_values(self):
        """ReportFormat has expected members."""
        assert hasattr(ReportFormat, "JSON")
