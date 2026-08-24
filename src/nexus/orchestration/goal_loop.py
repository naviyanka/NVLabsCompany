"""Goal-Gated Loop with Independent Judge - autonomous iteration mechanism.

Implements an autonomous iteration loop where agents work toward a goal
with a separate judge evaluating completion. Includes safety valves for
max iterations, budget limits, and consecutive parse failure detection.
"""

import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


@dataclass
class JudgeVerdict:
    """Verdict from a goal judge evaluating current progress.

    Attributes:
        is_complete: Whether the goal has been achieved.
        confidence: Confidence level from 0.0 to 1.0.
        reasoning: Human-readable explanation of the verdict.
    """

    is_complete: bool
    confidence: float
    reasoning: str


@dataclass
class GoalResult:
    """Outcome of a goal loop execution.

    Attributes:
        task_id: The task that was executed.
        success: Whether the goal was achieved.
        iterations_used: Number of iterations completed.
        final_output: The last output produced by execute_fn.
        judge_verdict: The final judge verdict reasoning.
        total_cost_cents: Cumulative cost across all iterations.
        stopped_reason: Why the loop stopped, if not by judge confirmation.
            One of: max_iterations, budget_exceeded, parse_failures, judge_confirmed.
    """

    task_id: uuid.UUID
    success: bool
    iterations_used: int
    final_output: Any
    judge_verdict: str
    total_cost_cents: int
    stopped_reason: str | None


@runtime_checkable
class GoalJudge(Protocol):
    """Protocol for goal judges that evaluate completion.

    Implementations must provide an evaluate method that inspects
    the current output and determines whether the goal is met.
    """

    async def evaluate(
        self, goal: str, current_output: Any, iteration: int
    ) -> JudgeVerdict:
        """Evaluate whether the goal has been achieved.

        Args:
            goal: The goal description being pursued.
            current_output: The current output from the execution function.
            iteration: The current iteration number (1-indexed).

        Returns:
            A JudgeVerdict indicating completion status.
        """
        ...


class HeuristicGoalJudge:
    """Goal judge using keyword matching and output length heuristics.

    Determines completion by checking whether the output contains
    any of the configured completion keywords and meets the minimum
    output length requirement.

    Example usage:
        judge = HeuristicGoalJudge(
            completion_keywords=["done", "complete", "finished"],
            min_output_length=50,
        )
        verdict = await judge.evaluate("Write a report", output, iteration=3)
    """

    def __init__(
        self,
        completion_keywords: list[str] | None = None,
        min_output_length: int = 10,
    ) -> None:
        """Initialize the heuristic judge.

        Args:
            completion_keywords: Keywords that indicate goal completion.
                Defaults to ["done", "complete", "finished", "success"].
            min_output_length: Minimum output string length to consider
                the output as potentially complete.
        """
        self._completion_keywords = completion_keywords or [
            "done",
            "complete",
            "finished",
            "success",
        ]
        self._min_output_length = min_output_length

    async def evaluate(
        self, goal: str, current_output: Any, iteration: int
    ) -> JudgeVerdict:
        """Evaluate completion using keyword matching and length heuristics.

        The output is considered complete when:
        1. The string representation meets the minimum length requirement.
        2. At least one completion keyword is found in the output.

        Args:
            goal: The goal description being pursued.
            current_output: The current output from the execution function.
            iteration: The current iteration number (1-indexed).

        Returns:
            A JudgeVerdict with is_complete=True if both conditions are met.
        """
        output_str = str(current_output)
        output_length = len(output_str)
        output_lower = output_str.lower()

        length_ok = output_length >= self._min_output_length
        keyword_found = any(
            kw.lower() in output_lower for kw in self._completion_keywords
        )

        if length_ok and keyword_found:
            matched = [
                kw for kw in self._completion_keywords if kw.lower() in output_lower
            ]
            return JudgeVerdict(
                is_complete=True,
                confidence=0.8,
                reasoning=(
                    f"Output meets minimum length ({output_length} >= "
                    f"{self._min_output_length}) and contains keyword(s): "
                    f"{matched}"
                ),
            )

        reasons: list[str] = []
        if not length_ok:
            reasons.append(
                f"Output too short ({output_length} < {self._min_output_length})"
            )
        if not keyword_found:
            reasons.append("No completion keywords found")

        return JudgeVerdict(
            is_complete=False,
            confidence=0.3,
            reasoning="; ".join(reasons),
        )


class GoalLoop:
    """Autonomous iteration loop with independent judge evaluation.

    Repeatedly calls an execution function and evaluates the output
    against a goal using an independent judge. Provides safety valves
    for max iterations, budget limits, and consecutive parse failures.

    Example usage:
        judge = HeuristicGoalJudge(completion_keywords=["done"])
        loop = GoalLoop(judge=judge, max_iterations=10, budget_limit_cents=5000)
        result = await loop.run(
            task_id=uuid.uuid4(),
            goal="Generate a summary report",
            execute_fn=my_agent_fn,
        )
        if result.success:
            print(f"Goal achieved in {result.iterations_used} iterations")
    """

    def __init__(
        self,
        judge: GoalJudge,
        max_iterations: int = 10,
        max_consecutive_parse_failures: int = 3,
        budget_limit_cents: int = 5000,
    ) -> None:
        """Initialize the goal loop.

        Args:
            judge: The judge that evaluates goal completion.
            max_iterations: Maximum number of iterations before stopping.
            max_consecutive_parse_failures: Maximum consecutive judge
                exceptions before auto-stopping.
            budget_limit_cents: Maximum cumulative cost in cents.
        """
        self._judge = judge
        self._max_iterations = max_iterations
        self._max_consecutive_parse_failures = max_consecutive_parse_failures
        self._budget_limit_cents = budget_limit_cents

    async def run(
        self,
        task_id: uuid.UUID,
        goal: str,
        execute_fn: Callable[[], Awaitable[tuple[Any, int]]],
    ) -> GoalResult:
        """Run the goal loop until completion or a safety valve triggers.

        Iterates by calling execute_fn, then passing the output to the
        judge for evaluation. Stops when:
        - Judge confirms goal is complete (success)
        - Max iterations reached
        - Budget limit exceeded
        - Too many consecutive parse failures from the judge

        Args:
            task_id: Identifier for this task execution.
            goal: The goal description to pursue.
            execute_fn: Async callable returning (output, cost_cents).

        Returns:
            A GoalResult with the final outcome and metadata.
        """
        total_cost = 0
        consecutive_parse_failures = 0
        final_output: Any = None
        judge_verdict_reasoning = ""
        iterations_used = 0

        for iteration in range(1, self._max_iterations + 1):
            iterations_used = iteration

            # Execute the work function
            try:
                output, cost_cents = await execute_fn()
            except Exception as exc:
                return GoalResult(
                    task_id=task_id,
                    success=False,
                    iterations_used=iterations_used,
                    final_output=final_output,
                    judge_verdict=(
                        f"execute_fn raised {type(exc).__name__}: {exc}"
                    ),
                    total_cost_cents=total_cost,
                    stopped_reason="execution_error",
                )

            total_cost += cost_cents
            final_output = output

            # Check budget after execution
            if total_cost > self._budget_limit_cents:
                return GoalResult(
                    task_id=task_id,
                    success=False,
                    iterations_used=iterations_used,
                    final_output=final_output,
                    judge_verdict=judge_verdict_reasoning or "Budget exceeded before evaluation",
                    total_cost_cents=total_cost,
                    stopped_reason="budget_exceeded",
                )

            # Evaluate with judge
            try:
                verdict = await self._judge.evaluate(goal, output, iteration)
                consecutive_parse_failures = 0
                judge_verdict_reasoning = verdict.reasoning

                if verdict.is_complete:
                    return GoalResult(
                        task_id=task_id,
                        success=True,
                        iterations_used=iterations_used,
                        final_output=final_output,
                        judge_verdict=verdict.reasoning,
                        total_cost_cents=total_cost,
                        stopped_reason="judge_confirmed",
                    )

            except Exception:
                consecutive_parse_failures += 1
                judge_verdict_reasoning = (
                    f"Judge raised exception (consecutive failures: "
                    f"{consecutive_parse_failures})"
                )

                if consecutive_parse_failures >= self._max_consecutive_parse_failures:
                    return GoalResult(
                        task_id=task_id,
                        success=False,
                        iterations_used=iterations_used,
                        final_output=final_output,
                        judge_verdict=judge_verdict_reasoning,
                        total_cost_cents=total_cost,
                        stopped_reason="parse_failures",
                    )

        # Max iterations exhausted
        return GoalResult(
            task_id=task_id,
            success=False,
            iterations_used=iterations_used,
            final_output=final_output,
            judge_verdict=judge_verdict_reasoning or "Max iterations reached",
            total_cost_cents=total_cost,
            stopped_reason="max_iterations",
        )


class LLMGoalJudge:
    """Goal judge that uses an LLM to evaluate whether a goal is achieved.

    Falls back to HeuristicGoalJudge on any LLM failure.

    Args:
        llm_callable: Async function that takes a prompt string and returns a response.
        fallback: Optional heuristic judge to use on failure.
    """

    def __init__(
        self,
        llm_callable: "Callable[[str], Awaitable[str]] | None" = None,
        fallback: "GoalJudge | None" = None,
    ) -> None:
        self._llm_callable = llm_callable
        self._fallback = fallback or HeuristicGoalJudge()

    async def evaluate(
        self, goal: str, current_output: Any, iteration: int
    ) -> JudgeVerdict:
        """Evaluate goal completion using LLM reasoning.

        Prompts the LLM with the goal and current output, asks whether
        the goal is achieved. Parses yes/no from the response.
        """
        if self._llm_callable is None:
            return await self._fallback.evaluate(goal, current_output, iteration)

        try:
            prompt = (
                f"You are evaluating whether a goal has been achieved.\n\n"
                f"GOAL: {goal}\n\n"
                f"CURRENT OUTPUT (iteration {iteration}):\n{str(current_output)[:3000]}\n\n"
                f"Has this goal been achieved? Answer ONLY with 'YES' or 'NO' followed by a brief reason."
            )
            response = await self._llm_callable(prompt)
            response_lower = response.strip().lower()

            is_complete = response_lower.startswith("yes")
            confidence = 0.9 if is_complete else 0.4

            return JudgeVerdict(
                is_complete=is_complete,
                confidence=confidence,
                reasoning=response.strip()[:200],
            )
        except Exception:
            return await self._fallback.evaluate(goal, current_output, iteration)
