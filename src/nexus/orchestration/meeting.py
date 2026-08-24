"""Virtual Meeting Rooms — synchronous multi-agent debate & consensus (from AI-Company).

Agents are gathered in a "room" where each gets the same prompt plus prior
responses. They iterate until consensus or max rounds. The synthesized result
represents the collective intelligence of the participating agents.

Usage:
    from nexus.orchestration.meeting import run_meeting

    result = await run_meeting(
        topic="Design the API for feature X",
        agents=[agent1, agent2, agent3],
        llm_fn=my_llm_callable,
        max_rounds=3,
    )
    print(result.consensus)  # The synthesized outcome
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class MeetingResult:
    """Outcome of a virtual meeting."""

    topic: str
    rounds: int
    participants: list[str]
    transcript: list[dict[str, str]]  # [{"agent": "name", "response": "..."}]
    consensus: str  # Synthesized final answer
    consensus_reached: bool


async def run_meeting(
    topic: str,
    agents: list[Any],
    llm_fn: Callable[[Any, str, str], Awaitable[str]],
    max_rounds: int = 3,
    context: str = "",
) -> MeetingResult:
    """Run a virtual meeting with multiple agents debating a topic.

    Each round, every agent sees the topic + all prior responses and contributes.
    After max_rounds (or if agents agree), a synthesis is produced.

    Args:
        topic: The meeting topic/question to debate.
        agents: List of Agent model instances to participate.
        llm_fn: Async callable(agent, system_prompt, user_prompt) -> response text.
        max_rounds: Maximum debate rounds.
        context: Optional additional context.

    Returns:
        MeetingResult with transcript and synthesized consensus.
    """
    transcript: list[dict[str, str]] = []
    participant_names = [a.name for a in agents]

    for round_num in range(1, max_rounds + 1):
        round_responses: list[str] = []

        for agent in agents:
            # Build prompt with prior discussion context
            prior_discussion = "\n".join(
                f"[{entry['agent']}]: {entry['response'][:500]}"
                for entry in transcript
            )

            prompt = f"MEETING TOPIC: {topic}\n\n"
            if context:
                prompt += f"CONTEXT: {context}\n\n"
            if prior_discussion:
                prompt += f"PRIOR DISCUSSION:\n{prior_discussion}\n\n"
            prompt += (
                f"Round {round_num}/{max_rounds}. "
                f"Share your perspective as {agent.role}. "
                f"If you agree with prior points, say 'I agree' and add refinements. "
                f"Be concise (2-3 sentences max)."
            )

            try:
                from nexus.api.routes.chat import _build_system_prompt
                system_prompt = _build_system_prompt(agent)
                response = await llm_fn(agent, system_prompt, prompt)
                transcript.append({"agent": agent.name, "response": response[:1000], "round": str(round_num)})
                round_responses.append(response)
            except Exception as e:
                transcript.append({"agent": agent.name, "response": f"[Error: {e}]", "round": str(round_num)})

        # Check for early consensus (all say "I agree")
        agree_count = sum(1 for r in round_responses if "i agree" in r.lower())
        if agree_count >= len(agents) - 1:  # All but one agree
            break

    # Synthesize consensus from the debate
    all_points = "\n".join(f"[{e['agent']}]: {e['response'][:300]}" for e in transcript)
    synthesis_prompt = (
        f"You are synthesizing a meeting outcome.\n\n"
        f"TOPIC: {topic}\n\n"
        f"DISCUSSION:\n{all_points}\n\n"
        f"Provide a clear, actionable consensus (3-5 sentences) that incorporates the best ideas from all participants."
    )

    consensus = ""
    if agents:
        try:
            from nexus.api.routes.chat import _build_system_prompt
            system_prompt = _build_system_prompt(agents[0])
            consensus = await llm_fn(agents[0], system_prompt, synthesis_prompt)
        except Exception:
            consensus = f"Meeting concluded after {round_num} rounds. See transcript for details."

    return MeetingResult(
        topic=topic,
        rounds=round_num,
        participants=participant_names,
        transcript=transcript,
        consensus=consensus,
        consensus_reached=agree_count >= len(agents) - 1 if 'agree_count' in dir() else False,
    )
