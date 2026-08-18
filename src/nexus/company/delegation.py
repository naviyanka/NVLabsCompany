"""Task delegation engine.

Handles finding the best agent for a task based on skill matching and capacity,
cascading delegations through organizational hierarchy, and tracking delegation state.
"""

import uuid
from typing import Any, Optional


class DelegationEngine:
    """Delegates tasks to the best-suited agents based on skills and capacity."""

    def __init__(self, db: Optional[Any] = None) -> None:
        """Initialize with optional database session for persistence.

        Args:
            db: Optional AsyncSession for persisting delegation records.
        """
        self.db = db
        self._delegations: dict[uuid.UUID, dict[str, Any]] = {}
        self._task_delegations: dict[uuid.UUID, list[dict[str, Any]]] = {}

    def find_best_delegate(
        self, task_title: str, task_skills: list[str], candidates: list
    ) -> tuple:
        """Score candidates by skill match and capacity.

        Uses Jaccard similarity on skills list for matching, with a
        preference for agents not in 'busy' status.

        Args:
            task_title: Title of the task to delegate.
            task_skills: Required skills for the task.
            candidates: List of agent instances to evaluate.

        Returns:
            Tuple of (best_agent, score). Returns (None, 0.0) if no candidates.
        """
        if not candidates:
            return (None, 0.0)

        best_agent = None
        best_score = -1.0

        task_skills_set = set(s.lower() for s in task_skills)

        for agent in candidates:
            agent_skills = set(
                s.lower() for s in (agent.skills or [])
            )

            # Jaccard similarity
            if task_skills_set or agent_skills:
                intersection = task_skills_set & agent_skills
                union = task_skills_set | agent_skills
                skill_score = len(intersection) / len(union) if union else 0.0
            else:
                skill_score = 0.0

            # Capacity bonus: prefer agents not busy
            capacity_bonus = 0.2 if getattr(agent, "status", "idle") != "busy" else 0.0

            total_score = skill_score + capacity_bonus

            if total_score > best_score:
                best_score = total_score
                best_agent = agent

        # Normalize score to 0-1 range (max possible is 1.2)
        normalized_score = min(best_score / 1.2, 1.0) if best_score > 0 else 0.0

        return (best_agent, normalized_score)

    async def delegate_task(
        self,
        task_id: uuid.UUID,
        from_agent_id: uuid.UUID,
        to_agent_id: uuid.UUID,
        reason: str,
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Create delegation record.

        Args:
            task_id: ID of the task being delegated.
            from_agent_id: ID of the delegating agent.
            to_agent_id: ID of the receiving agent.
            reason: Reason for the delegation.
            company_id: Company isolation scope.

        Returns:
            Dict with delegation_id and status.
        """
        delegation_id = uuid.uuid4()
        record = {
            "delegation_id": delegation_id,
            "task_id": task_id,
            "from_agent_id": from_agent_id,
            "to_agent_id": to_agent_id,
            "reason": reason,
            "company_id": company_id,
            "status": "delegated",
        }

        self._delegations[delegation_id] = record

        # Track delegation chain per task
        if task_id not in self._task_delegations:
            self._task_delegations[task_id] = []
        self._task_delegations[task_id].append(record)

        return {"delegation_id": delegation_id, "status": "delegated"}

    def cascade_delegation(
        self, task_title: str, task_skills: list[str], chain: list
    ) -> list[dict[str, Any]]:
        """Walk chain (e.g. CEO -> CTO -> Engineer), find best at each level.

        At each level, the current agent delegates to the best match among
        the next level candidates.

        Args:
            task_title: Title of the task.
            task_skills: Required skills for the task.
            chain: List of lists, where each inner list is the candidates
                   at that organizational level.

        Returns:
            List of delegation steps with from/to agent info and scores.
        """
        steps: list[dict[str, Any]] = []

        for i in range(len(chain) - 1):
            from_candidates = chain[i] if isinstance(chain[i], list) else [chain[i]]
            to_candidates = chain[i + 1] if isinstance(chain[i + 1], list) else [chain[i + 1]]

            # Use the first from the current level as the delegator
            from_agent = from_candidates[0] if from_candidates else None

            # Find best delegate at the next level
            best_agent, score = self.find_best_delegate(
                task_title, task_skills, to_candidates
            )

            steps.append({
                "level": i,
                "from_agent_id": from_agent.id if from_agent else None,
                "from_agent_name": from_agent.name if from_agent else None,
                "to_agent_id": best_agent.id if best_agent else None,
                "to_agent_name": best_agent.name if best_agent else None,
                "score": score,
                "task_title": task_title,
            })

        return steps

    async def track_delegation(
        self, delegation_id: uuid.UUID
    ) -> dict[str, Any]:
        """Return delegation status.

        Args:
            delegation_id: The ID of the delegation to track.

        Returns:
            Dict with delegation details or not_found status.
        """
        record = self._delegations.get(delegation_id)
        if record is None:
            return {"delegation_id": delegation_id, "status": "not_found"}
        return record

    async def get_delegation_chain(
        self, task_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """Return full delegation history for a task.

        Args:
            task_id: The task to get delegation history for.

        Returns:
            List of delegation records in order.
        """
        return self._task_delegations.get(task_id, [])
