"""Tests for Goal-Gated Loop with Independent Judge."""

import uuid

import pytest

from nexus.orchestration.goal_loop import (
    GoalJudge,
    GoalLoop,
    GoalResult,
    HeuristicGoalJudge,
    JudgeVerdict,
)


@pytest.fixture
def task_id() -> uuid.UUID:
    """Create a test task UUID."""
    return uuid.uuid4()


@pytest.fixture
def heuristic_judge() -> HeuristicGoalJudge:
    """Create a HeuristicGoalJudge with default settings."""
    return HeuristicGoalJudge()


class TestGoalLoopSuccessFirstIteration:
    """Tests for goal loop succeeding on the first iteration."""

    @pytest.mark.asyncio
    async def test_success_on_first_iteration(self, task_id: uuid.UUID) -> None:
        """Goal loop returns success when judge confirms on first iteration."""

        class AlwaysCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=True, confidence=1.0, reasoning="Goal achieved"
                )

        loop = GoalLoop(judge=AlwaysCompleteJudge(), max_iterations=10)

        async def execute_fn() -> tuple[str, int]:
            return ("result output", 100)

        result = await loop.run(task_id=task_id, goal="Do something", execute_fn=execute_fn)

        assert result.success is True
        assert result.iterations_used == 1
        assert result.final_output == "result output"
        assert result.total_cost_cents == 100
        assert result.stopped_reason == "judge_confirmed"
        assert result.task_id == task_id

    @pytest.mark.asyncio
    async def test_success_result_contains_judge_verdict(
        self, task_id: uuid.UUID
    ) -> None:
        """GoalResult contains the judge's reasoning on success."""

        class ConfirmJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=True,
                    confidence=0.95,
                    reasoning="All criteria met",
                )

        loop = GoalLoop(judge=ConfirmJudge(), max_iterations=5)

        async def execute_fn() -> tuple[str, int]:
            return ("done", 50)

        result = await loop.run(task_id=task_id, goal="Complete task", execute_fn=execute_fn)

        assert result.judge_verdict == "All criteria met"


class TestGoalLoopSuccessAfterMultipleIterations:
    """Tests for goal loop succeeding after N iterations."""

    @pytest.mark.asyncio
    async def test_success_after_three_iterations(self, task_id: uuid.UUID) -> None:
        """Goal loop succeeds when judge confirms after multiple iterations."""
        call_count = 0

        class DelayedCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                if iteration < 3:
                    return JudgeVerdict(
                        is_complete=False,
                        confidence=0.3,
                        reasoning="Not yet complete",
                    )
                return JudgeVerdict(
                    is_complete=True,
                    confidence=0.9,
                    reasoning="Goal now complete",
                )

        loop = GoalLoop(judge=DelayedCompleteJudge(), max_iterations=10)

        async def execute_fn() -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            return (f"output iteration {call_count}", 25)

        result = await loop.run(task_id=task_id, goal="Build report", execute_fn=execute_fn)

        assert result.success is True
        assert result.iterations_used == 3
        assert result.total_cost_cents == 75
        assert result.final_output == "output iteration 3"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_cost_accumulates_across_iterations(
        self, task_id: uuid.UUID
    ) -> None:
        """Total cost is the sum across all iterations."""

        class NthIterationJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                if iteration >= 4:
                    return JudgeVerdict(
                        is_complete=True, confidence=1.0, reasoning="Done"
                    )
                return JudgeVerdict(
                    is_complete=False, confidence=0.2, reasoning="Working"
                )

        loop = GoalLoop(judge=NthIterationJudge(), max_iterations=10)

        async def execute_fn() -> tuple[str, int]:
            return ("output", 30)

        result = await loop.run(task_id=task_id, goal="Accumulate", execute_fn=execute_fn)

        assert result.success is True
        assert result.iterations_used == 4
        assert result.total_cost_cents == 120


class TestGoalLoopMaxIterationsStop:
    """Tests for max_iterations safety valve."""

    @pytest.mark.asyncio
    async def test_stops_at_max_iterations(self, task_id: uuid.UUID) -> None:
        """Goal loop stops with stopped_reason='max_iterations' when limit hit."""

        class NeverCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=False,
                    confidence=0.1,
                    reasoning="Still working",
                )

        loop = GoalLoop(judge=NeverCompleteJudge(), max_iterations=5)

        async def execute_fn() -> tuple[str, int]:
            return ("partial", 10)

        result = await loop.run(task_id=task_id, goal="Impossible goal", execute_fn=execute_fn)

        assert result.success is False
        assert result.iterations_used == 5
        assert result.stopped_reason == "max_iterations"
        assert result.total_cost_cents == 50

    @pytest.mark.asyncio
    async def test_max_iterations_one(self, task_id: uuid.UUID) -> None:
        """Goal loop stops after 1 iteration when max_iterations=1."""

        class NeverCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=False, confidence=0.0, reasoning="No"
                )

        loop = GoalLoop(judge=NeverCompleteJudge(), max_iterations=1)

        async def execute_fn() -> tuple[str, int]:
            return ("one shot", 5)

        result = await loop.run(task_id=task_id, goal="One try", execute_fn=execute_fn)

        assert result.success is False
        assert result.iterations_used == 1
        assert result.stopped_reason == "max_iterations"


class TestGoalLoopBudgetExhaustion:
    """Tests for budget limit safety valve."""

    @pytest.mark.asyncio
    async def test_stops_on_budget_exceeded(self, task_id: uuid.UUID) -> None:
        """Goal loop stops with stopped_reason='budget_exceeded' when limit hit."""

        class NeverCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=False, confidence=0.2, reasoning="Not done"
                )

        loop = GoalLoop(
            judge=NeverCompleteJudge(),
            max_iterations=100,
            budget_limit_cents=100,
        )

        async def execute_fn() -> tuple[str, int]:
            return ("expensive output", 60)

        result = await loop.run(task_id=task_id, goal="Expensive goal", execute_fn=execute_fn)

        assert result.success is False
        assert result.stopped_reason == "budget_exceeded"
        assert result.total_cost_cents > 100

    @pytest.mark.asyncio
    async def test_budget_stops_before_max_iterations(
        self, task_id: uuid.UUID
    ) -> None:
        """Budget exhaustion stops the loop well before max iterations."""

        class NeverCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=False, confidence=0.1, reasoning="Nope"
                )

        loop = GoalLoop(
            judge=NeverCompleteJudge(),
            max_iterations=50,
            budget_limit_cents=150,
        )

        async def execute_fn() -> tuple[str, int]:
            return ("output", 80)

        result = await loop.run(task_id=task_id, goal="Budget test", execute_fn=execute_fn)

        assert result.success is False
        assert result.stopped_reason == "budget_exceeded"
        assert result.iterations_used == 2
        assert result.total_cost_cents == 160


class TestGoalLoopParseFailures:
    """Tests for consecutive parse failure auto-stop."""

    @pytest.mark.asyncio
    async def test_stops_on_consecutive_parse_failures(
        self, task_id: uuid.UUID
    ) -> None:
        """Goal loop stops with stopped_reason='parse_failures' after consecutive errors."""

        class BrokenJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                raise ValueError("Cannot parse judge response")

        loop = GoalLoop(
            judge=BrokenJudge(),
            max_iterations=10,
            max_consecutive_parse_failures=3,
        )

        async def execute_fn() -> tuple[str, int]:
            return ("output", 10)

        result = await loop.run(task_id=task_id, goal="Parse test", execute_fn=execute_fn)

        assert result.success is False
        assert result.stopped_reason == "parse_failures"
        assert result.iterations_used == 3
        assert result.total_cost_cents == 30


class TestGoalLoopExecutionError:
    """Tests for execute_fn exception handling."""

    @pytest.mark.asyncio
    async def test_stops_on_execute_fn_exception(self, task_id: uuid.UUID) -> None:
        """Goal loop returns execution_error when execute_fn raises."""

        class NeverCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=False, confidence=0.1, reasoning="Not done"
                )

        loop = GoalLoop(judge=NeverCompleteJudge(), max_iterations=10)

        async def execute_fn() -> tuple[str, int]:
            raise RuntimeError("LLM API connection failed")

        result = await loop.run(task_id=task_id, goal="Crash test", execute_fn=execute_fn)

        assert result.success is False
        assert result.stopped_reason == "execution_error"
        assert result.iterations_used == 1
        assert result.total_cost_cents == 0
        assert "RuntimeError" in result.judge_verdict
        assert "LLM API connection failed" in result.judge_verdict

    @pytest.mark.asyncio
    async def test_execution_error_preserves_prior_output(
        self, task_id: uuid.UUID
    ) -> None:
        """If execute_fn fails on iteration 2+, prior output is in final_output."""
        call_count = 0

        class NeverCompleteJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                return JudgeVerdict(
                    is_complete=False, confidence=0.2, reasoning="Pending"
                )

        loop = GoalLoop(judge=NeverCompleteJudge(), max_iterations=10)

        async def execute_fn() -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise ConnectionError("Network timeout")
            return (f"output-{call_count}", 50)

        result = await loop.run(task_id=task_id, goal="Net fail", execute_fn=execute_fn)

        assert result.success is False
        assert result.stopped_reason == "execution_error"
        assert result.iterations_used == 2
        assert result.final_output == "output-1"
        assert result.total_cost_cents == 50

    @pytest.mark.asyncio
    async def test_non_consecutive_failures_do_not_trigger_stop(
        self, task_id: uuid.UUID
    ) -> None:
        """Parse failures are reset when judge succeeds between them."""
        call_count = 0

        class IntermittentJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                # Fail on iterations 1, 2 then succeed on 3, then fail on 4, 5
                # then succeed on 6 (confirms done)
                if iteration in (1, 2, 4, 5):
                    raise RuntimeError("Parse error")
                if iteration == 6:
                    return JudgeVerdict(
                        is_complete=True, confidence=0.9, reasoning="Finally done"
                    )
                return JudgeVerdict(
                    is_complete=False, confidence=0.5, reasoning="Keep going"
                )

        loop = GoalLoop(
            judge=IntermittentJudge(),
            max_iterations=10,
            max_consecutive_parse_failures=3,
        )

        async def execute_fn() -> tuple[str, int]:
            nonlocal call_count
            call_count += 1
            return (f"iter {call_count}", 10)

        result = await loop.run(task_id=task_id, goal="Intermittent", execute_fn=execute_fn)

        assert result.success is True
        assert result.iterations_used == 6

    @pytest.mark.asyncio
    async def test_custom_parse_failure_limit(self, task_id: uuid.UUID) -> None:
        """Custom max_consecutive_parse_failures is respected."""

        class BrokenJudge:
            async def evaluate(
                self, goal: str, current_output: object, iteration: int
            ) -> JudgeVerdict:
                raise TypeError("Always broken")

        loop = GoalLoop(
            judge=BrokenJudge(),
            max_iterations=20,
            max_consecutive_parse_failures=5,
        )

        async def execute_fn() -> tuple[str, int]:
            return ("output", 5)

        result = await loop.run(task_id=task_id, goal="Custom limit", execute_fn=execute_fn)

        assert result.success is False
        assert result.stopped_reason == "parse_failures"
        assert result.iterations_used == 5


class TestHeuristicGoalJudgeKeywordDetection:
    """Tests for HeuristicGoalJudge keyword matching."""

    @pytest.mark.asyncio
    async def test_keyword_found_and_length_met(self) -> None:
        """Returns is_complete=True when keyword found and length sufficient."""
        judge = HeuristicGoalJudge(
            completion_keywords=["done", "finished"],
            min_output_length=10,
        )

        verdict = await judge.evaluate(
            goal="Write report",
            current_output="The task is done and the report is ready",
            iteration=1,
        )

        assert verdict.is_complete is True
        assert verdict.confidence == 0.8
        assert "done" in verdict.reasoning.lower()

    @pytest.mark.asyncio
    async def test_keyword_not_found(self) -> None:
        """Returns is_complete=False when no keywords found."""
        judge = HeuristicGoalJudge(
            completion_keywords=["done", "finished"],
            min_output_length=5,
        )

        verdict = await judge.evaluate(
            goal="Write code",
            current_output="Still working on the implementation",
            iteration=2,
        )

        assert verdict.is_complete is False
        assert "No completion keywords found" in verdict.reasoning

    @pytest.mark.asyncio
    async def test_length_not_met(self) -> None:
        """Returns is_complete=False when output is too short."""
        judge = HeuristicGoalJudge(
            completion_keywords=["done"],
            min_output_length=100,
        )

        verdict = await judge.evaluate(
            goal="Generate text",
            current_output="done",
            iteration=1,
        )

        assert verdict.is_complete is False
        assert "too short" in verdict.reasoning.lower()

    @pytest.mark.asyncio
    async def test_case_insensitive_keyword_matching(self) -> None:
        """Keyword matching is case-insensitive."""
        judge = HeuristicGoalJudge(
            completion_keywords=["COMPLETE"],
            min_output_length=5,
        )

        verdict = await judge.evaluate(
            goal="Finish",
            current_output="The task is complete now.",
            iteration=1,
        )

        assert verdict.is_complete is True

    @pytest.mark.asyncio
    async def test_default_keywords(self) -> None:
        """Default keywords include done, complete, finished, success."""
        judge = HeuristicGoalJudge(min_output_length=5)

        for keyword in ["done", "complete", "finished", "success"]:
            verdict = await judge.evaluate(
                goal="Test",
                current_output=f"The operation is {keyword} and verified",
                iteration=1,
            )
            assert verdict.is_complete is True, f"Expected True for '{keyword}'"


class TestHeuristicGoalJudgeMinOutputLength:
    """Tests for HeuristicGoalJudge minimum output length logic."""

    @pytest.mark.asyncio
    async def test_exactly_min_length_passes(self) -> None:
        """Output at exactly min_output_length passes the length check."""
        judge = HeuristicGoalJudge(
            completion_keywords=["x"],
            min_output_length=5,
        )

        verdict = await judge.evaluate(
            goal="Test",
            current_output="x" * 5,
            iteration=1,
        )

        assert verdict.is_complete is True

    @pytest.mark.asyncio
    async def test_below_min_length_fails(self) -> None:
        """Output below min_output_length fails even with keyword present."""
        judge = HeuristicGoalJudge(
            completion_keywords=["ok"],
            min_output_length=50,
        )

        verdict = await judge.evaluate(
            goal="Test",
            current_output="ok",
            iteration=1,
        )

        assert verdict.is_complete is False

    @pytest.mark.asyncio
    async def test_both_conditions_must_be_met(self) -> None:
        """Both keyword and length must be satisfied for completion."""
        judge = HeuristicGoalJudge(
            completion_keywords=["done"],
            min_output_length=20,
        )

        # Long but no keyword
        verdict = await judge.evaluate(
            goal="Test",
            current_output="A" * 100,
            iteration=1,
        )
        assert verdict.is_complete is False

        # Keyword but short
        verdict = await judge.evaluate(
            goal="Test",
            current_output="done",
            iteration=1,
        )
        assert verdict.is_complete is False

        # Both conditions met
        verdict = await judge.evaluate(
            goal="Test",
            current_output="The operation is done and everything works fine",
            iteration=1,
        )
        assert verdict.is_complete is True


class TestGoalResultDataclass:
    """Tests for the GoalResult dataclass."""

    def test_goal_result_fields(self) -> None:
        """GoalResult has all expected fields."""
        tid = uuid.uuid4()
        result = GoalResult(
            task_id=tid,
            success=True,
            iterations_used=3,
            final_output="final",
            judge_verdict="All good",
            total_cost_cents=150,
            stopped_reason="judge_confirmed",
        )

        assert result.task_id == tid
        assert result.success is True
        assert result.iterations_used == 3
        assert result.final_output == "final"
        assert result.judge_verdict == "All good"
        assert result.total_cost_cents == 150
        assert result.stopped_reason == "judge_confirmed"

    def test_goal_result_none_stopped_reason(self) -> None:
        """GoalResult supports None stopped_reason."""
        result = GoalResult(
            task_id=uuid.uuid4(),
            success=False,
            iterations_used=0,
            final_output=None,
            judge_verdict="",
            total_cost_cents=0,
            stopped_reason=None,
        )

        assert result.stopped_reason is None


class TestJudgeVerdictDataclass:
    """Tests for the JudgeVerdict dataclass."""

    def test_judge_verdict_fields(self) -> None:
        """JudgeVerdict has all expected fields."""
        verdict = JudgeVerdict(
            is_complete=True,
            confidence=0.95,
            reasoning="Goal achieved",
        )

        assert verdict.is_complete is True
        assert verdict.confidence == 0.95
        assert verdict.reasoning == "Goal achieved"


class TestGoalJudgeProtocol:
    """Tests for GoalJudge protocol compliance."""

    def test_heuristic_judge_is_goal_judge(self) -> None:
        """HeuristicGoalJudge satisfies the GoalJudge protocol."""
        judge = HeuristicGoalJudge()
        assert isinstance(judge, GoalJudge)
