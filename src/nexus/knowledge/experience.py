"""Experience Manager - agent experience recording and pattern extraction.

Enables agents to record their task experiences, find similar past experiences
for learning, and extract success patterns across the organization.
"""

import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.memory.retriever import search as bm25_search
from nexus.models.knowledge import ExperienceRecord


class ExperienceManager:
    """Manager for recording, retrieving, and analyzing agent experiences.

    The ExperienceManager provides a structured way for agents to learn from
    past task executions. It records outcomes, approaches, and lessons learned,
    then makes this knowledge searchable for future reference.

    All operations are scoped by company_id to maintain multi-tenant isolation.

    Attributes:
        db: Async database session for persistence operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize ExperienceManager with a database session.

        Args:
            db: An async SQLAlchemy session for database operations.
        """
        self.db = db

    async def record_experience(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        task_id: uuid.UUID,
        outcome: str,
        approach: str,
        result_quality: float,
        lessons_learned: str,
        tags: list[str],
    ) -> ExperienceRecord:
        """Record a new experience from a completed task.

        Stores the agent's experience including what approach was taken,
        the outcome achieved, quality assessment, and any lessons learned.

        Args:
            company_id: Company scope for the experience.
            agent_id: UUID of the agent that completed the task.
            task_id: UUID of the task that was completed.
            outcome: Outcome classification ('success', 'failure', 'partial').
            approach: Description of the approach taken.
            result_quality: Quality score (0.0 to 1.0).
            lessons_learned: Free-text description of lessons learned.
            tags: Tags for categorization and filtering.

        Returns:
            The newly created ExperienceRecord instance.
        """
        record = ExperienceRecord(
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
            outcome=outcome,
            approach=approach,
            result_quality=result_quality,
            lessons_learned=lessons_learned,
            tags=tags,
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def find_similar_experiences(
        self,
        company_id: uuid.UUID,
        description: str,
        agent_id: Optional[uuid.UUID] = None,
        team_scope: bool = False,
        top_k: int = 5,
    ) -> list[ExperienceRecord]:
        """Find experiences similar to a given description.

        Searches past experiences using BM25 on the combined approach and
        lessons_learned text. Can be scoped to a specific agent or broadened
        to team scope.

        Args:
            company_id: Company scope for the search.
            description: Description of the current task/situation to match against.
            agent_id: Optional agent ID to filter experiences by a specific agent.
            team_scope: If True, search across all agents (ignore agent_id filter).
            top_k: Number of top matching experiences to return.

        Returns:
            List of ExperienceRecord instances ranked by relevance.
        """
        # Build query for experiences in this company
        statement = select(ExperienceRecord).where(
            ExperienceRecord.company_id == company_id
        )

        if agent_id and not team_scope:
            statement = statement.where(ExperienceRecord.agent_id == agent_id)

        result = await self.db.exec(statement)
        experiences = list(result.all())

        if not experiences:
            return []

        # Build search corpus from approach + lessons_learned
        memories: list[str] = []
        for exp in experiences:
            text_parts: list[str] = []
            if exp.approach:
                text_parts.append(exp.approach)
            if exp.lessons_learned:
                text_parts.append(exp.lessons_learned)
            memories.append(" ".join(text_parts) if text_parts else "")

        # Use BM25 search for relevance ranking
        ranked_results = bm25_search(description, memories, top_k=top_k)

        # Return experiences in ranked order
        return [experiences[idx] for idx, _score in ranked_results]

    async def get_success_patterns(
        self,
        company_id: uuid.UUID,
        tag_filter: Optional[str] = None,
    ) -> list[dict]:
        """Extract success patterns from past experiences.

        Aggregates successful experiences to identify common approaches
        and lessons. Groups by tags and extracts recurring themes.

        Args:
            company_id: Company scope for pattern extraction.
            tag_filter: Optional tag to filter experiences by.

        Returns:
            List of pattern dicts with keys: 'tag', 'count', 'avg_quality',
            'common_approaches', 'key_lessons'.
        """
        # Fetch successful experiences
        statement = select(ExperienceRecord).where(
            ExperienceRecord.company_id == company_id,
            ExperienceRecord.outcome == "success",
        )
        result = await self.db.exec(statement)
        experiences = list(result.all())

        if not experiences:
            return []

        # Apply tag filter if specified
        if tag_filter:
            experiences = [
                e for e in experiences if e.tags and tag_filter in e.tags
            ]

        if not experiences:
            return []

        # Group experiences by tags
        tag_groups: dict[str, list[ExperienceRecord]] = defaultdict(list)
        for exp in experiences:
            if exp.tags:
                for tag in exp.tags:
                    tag_groups[tag].append(exp)
            else:
                tag_groups["untagged"].append(exp)

        # Extract patterns from each group
        patterns: list[dict] = []
        for tag, group_exps in tag_groups.items():
            # Calculate average quality
            quality_scores = [
                e.result_quality for e in group_exps if e.result_quality is not None
            ]
            avg_quality = (
                sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
            )

            # Collect approaches and lessons
            approaches = [e.approach for e in group_exps if e.approach]
            lessons = [e.lessons_learned for e in group_exps if e.lessons_learned]

            patterns.append({
                "tag": tag,
                "count": len(group_exps),
                "avg_quality": round(avg_quality, 3),
                "common_approaches": approaches[:5],  # Top 5 approaches
                "key_lessons": lessons[:5],  # Top 5 lessons
            })

        # Sort by count descending (most common patterns first)
        patterns.sort(key=lambda p: p["count"], reverse=True)
        return patterns

    async def share_experience(
        self,
        experience_id: uuid.UUID,
        target_team_id: uuid.UUID,
    ) -> ExperienceRecord:
        """Make an experience visible to a target team scope.

        Updates the experience record's metadata to indicate it has been
        shared with a specific team, making it discoverable in team-scoped
        searches.

        Args:
            experience_id: UUID of the experience to share.
            target_team_id: UUID of the team to share with.

        Returns:
            The updated ExperienceRecord instance.

        Raises:
            ValueError: If the experience_id does not exist.
        """
        statement = select(ExperienceRecord).where(
            ExperienceRecord.id == experience_id
        )
        result = await self.db.exec(statement)
        record = result.first()

        if record is None:
            raise ValueError(f"Experience record not found: {experience_id}")

        # Add team sharing info to tags
        share_tag = f"shared:team:{target_team_id}"
        if record.tags is None:
            record.tags = [share_tag]
        elif share_tag not in record.tags:
            record.tags = record.tags + [share_tag]

        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record
