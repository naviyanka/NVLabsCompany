"""Benchmark definitions for model evaluation.

Provides dataclasses for defining test cases and organizing them into
benchmarks and benchmark suites. Supports serialization to/from dicts
for JSON persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TestCase:
    """A single test case for model evaluation.

    Attributes:
        input: The input prompt or query to send to the model.
        expected_output: The expected/ground-truth output for comparison.
        metadata: Additional metadata about this test case.
        tags: Tags for filtering and categorization.
    """

    input: str
    expected_output: str
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the test case to a dictionary.

        Returns:
            Dictionary representation of the test case.
        """
        return {
            "input": self.input,
            "expected_output": self.expected_output,
            "metadata": self.metadata,
            "tags": list(self.tags),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TestCase:
        """Create a TestCase from a dictionary.

        Args:
            data: Dictionary with test case fields.

        Returns:
            A new TestCase instance.
        """
        return cls(
            input=data["input"],
            expected_output=data["expected_output"],
            metadata=data.get("metadata", {}),
            tags=data.get("tags", []),
        )


@dataclass
class Benchmark:
    """A named collection of test cases for evaluating a specific capability.

    Attributes:
        name: Descriptive name for this benchmark.
        description: Detailed description of what this benchmark measures.
        test_cases: List of test cases in this benchmark.
        created_at: Timestamp when this benchmark was created.
    """

    name: str
    description: str
    test_cases: list[TestCase] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def add_test_case(self, test_case: TestCase) -> None:
        """Add a test case to this benchmark.

        Args:
            test_case: The test case to add.
        """
        self.test_cases.append(test_case)

    def filter_by_tags(self, tags: list[str]) -> list[TestCase]:
        """Filter test cases that have at least one of the specified tags.

        Args:
            tags: Tags to filter by.

        Returns:
            List of test cases matching at least one tag.
        """
        tag_set = set(tags)
        return [tc for tc in self.test_cases if tag_set & set(tc.tags)]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the benchmark to a dictionary.

        Returns:
            Dictionary representation of the benchmark.
        """
        return {
            "name": self.name,
            "description": self.description,
            "test_cases": [tc.to_dict() for tc in self.test_cases],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Benchmark:
        """Create a Benchmark from a dictionary.

        Args:
            data: Dictionary with benchmark fields.

        Returns:
            A new Benchmark instance.
        """
        return cls(
            name=data["name"],
            description=data["description"],
            test_cases=[TestCase.from_dict(tc) for tc in data.get("test_cases", [])],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class BenchmarkSuite:
    """A collection of benchmarks grouped for comprehensive evaluation.

    Supports filtering across all benchmarks by tags and serialization
    to/from dicts for JSON persistence.

    Attributes:
        name: Name of the benchmark suite.
        description: Description of the suite's purpose.
        benchmarks: List of benchmarks in this suite.
    """

    name: str
    description: str
    benchmarks: list[Benchmark] = field(default_factory=list)

    def add_benchmark(self, benchmark: Benchmark) -> None:
        """Add a benchmark to this suite.

        Args:
            benchmark: The benchmark to add.
        """
        self.benchmarks.append(benchmark)

    def get_all_test_cases(self) -> list[TestCase]:
        """Get all test cases across all benchmarks.

        Returns:
            Flattened list of all test cases.
        """
        cases: list[TestCase] = []
        for benchmark in self.benchmarks:
            cases.extend(benchmark.test_cases)
        return cases

    def filter_by_tags(self, tags: list[str]) -> list[TestCase]:
        """Filter test cases across all benchmarks by tags.

        Args:
            tags: Tags to filter by.

        Returns:
            List of test cases matching at least one tag.
        """
        tag_set = set(tags)
        results: list[TestCase] = []
        for benchmark in self.benchmarks:
            for tc in benchmark.test_cases:
                if tag_set & set(tc.tags):
                    results.append(tc)
        return results

    def to_dict(self) -> dict[str, Any]:
        """Serialize the benchmark suite to a dictionary.

        Returns:
            Dictionary representation of the suite.
        """
        return {
            "name": self.name,
            "description": self.description,
            "benchmarks": [b.to_dict() for b in self.benchmarks],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BenchmarkSuite:
        """Create a BenchmarkSuite from a dictionary.

        Args:
            data: Dictionary with suite fields.

        Returns:
            A new BenchmarkSuite instance.
        """
        return cls(
            name=data["name"],
            description=data["description"],
            benchmarks=[Benchmark.from_dict(b) for b in data.get("benchmarks", [])],
        )
