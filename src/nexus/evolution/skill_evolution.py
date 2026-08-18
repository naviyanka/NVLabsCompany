"""Skill Evolution - versioned skill management with approval-gated promotion.

Manages the lifecycle of skill versions: creating new versions, tracking
performance, comparing versions, and promoting improvements. All promotions
require explicit approval gates.
"""

import uuid
from datetime import datetime, timezone
from typing import Any


class SkillEvolution:
    """Manages skill version lifecycle with approval-gated promotion.

    Tracks skill versions, their performance metrics, and enables comparison
    between versions. Promotion to active status ALWAYS requires an approval_id.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize skill evolution manager.

        Args:
            db: Optional async database session for persistence.
        """
        self.db = db
        self._versions: list[dict[str, Any]] = []

    async def create_version(
        self,
        company_id: uuid.UUID,
        skill_id: uuid.UUID,
        prompt_template: str,
    ) -> dict[str, Any]:
        """Create a new skill version record.

        Args:
            company_id: The company owning the skill.
            skill_id: The skill to create a new version for.
            prompt_template: The new prompt template for this version.

        Returns:
            The created version record.
        """
        # Determine version number
        existing_versions = [
            v for v in self._versions
            if v["skill_id"] == str(skill_id) and v["company_id"] == str(company_id)
        ]
        version_number = len(existing_versions) + 1

        version_record = {
            "id": str(uuid.uuid4()),
            "company_id": str(company_id),
            "skill_id": str(skill_id),
            "version_number": version_number,
            "prompt_template": prompt_template,
            "performance_score": None,
            "is_active": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._versions.append(version_record)
        return version_record

    def track_performance(
        self,
        version_id: uuid.UUID,
        task_results: list[dict[str, Any]],
    ) -> float:
        """Update performance score for a version based on task results.

        Args:
            version_id: The version to update.
            task_results: List of task result dicts with 'score' field.

        Returns:
            The new performance score (average of task scores).
        """
        if not task_results:
            return 0.0

        scores = [r.get("score", 0.0) for r in task_results]
        new_score = sum(scores) / len(scores)

        # Update in-memory record
        version_str = str(version_id)
        for version in self._versions:
            if version["id"] == version_str:
                version["performance_score"] = new_score
                break

        return new_score

    def compare_versions(
        self,
        version_a: dict[str, Any],
        version_b: dict[str, Any],
    ) -> dict[str, Any]:
        """Compare two skill versions.

        Args:
            version_a: First version record.
            version_b: Second version record.

        Returns:
            Comparison dict with metrics and recommendation.
        """
        score_a = version_a.get("performance_score") or 0.0
        score_b = version_b.get("performance_score") or 0.0

        if score_a > 0:
            improvement = ((score_b - score_a) / score_a) * 100
        else:
            improvement = 0.0

        return {
            "version_a": {
                "id": version_a.get("id"),
                "version_number": version_a.get("version_number"),
                "performance_score": score_a,
            },
            "version_b": {
                "id": version_b.get("id"),
                "version_number": version_b.get("version_number"),
                "performance_score": score_b,
            },
            "improvement_percent": improvement,
            "better_version": "b" if score_b > score_a else "a" if score_a > score_b else "equal",
        }

    async def promote_version(
        self,
        version_id: uuid.UUID,
        approval_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Promote a skill version to active status.

        CRITICAL: Raises ValueError if approval_id is None. This is the
        governance gate that prevents auto-promotion without human approval.

        Args:
            version_id: The version to promote.
            approval_id: The approval authorizing this promotion. MUST NOT be None.

        Returns:
            The promoted version record.

        Raises:
            ValueError: If approval_id is None (governance gate violation).
        """
        if approval_id is None:
            raise ValueError("Approval required: approval_id must not be None")

        version_str = str(version_id)
        promoted_version = None

        for version in self._versions:
            if version["id"] == version_str:
                # Deactivate other versions of the same skill
                skill_id = version["skill_id"]
                company_id = version["company_id"]
                for v in self._versions:
                    if v["skill_id"] == skill_id and v["company_id"] == company_id:
                        v["is_active"] = False

                # Activate this version
                version["is_active"] = True
                promoted_version = version
                break

        if promoted_version is None:
            raise ValueError(f"Version {version_id} not found")

        return {
            **promoted_version,
            "approval_id": str(approval_id),
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        }

    async def rollback_version(
        self,
        skill_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Reactivate the previous version of a skill.

        Args:
            skill_id: The skill to roll back.
            company_id: The company owning the skill.

        Returns:
            The reactivated version record.
        """
        skill_versions = [
            v for v in self._versions
            if v["skill_id"] == str(skill_id) and v["company_id"] == str(company_id)
        ]

        if len(skill_versions) < 2:
            raise ValueError(f"No previous version available for skill {skill_id}")

        # Sort by version number
        skill_versions.sort(key=lambda v: v["version_number"])

        # Deactivate current active version
        for v in skill_versions:
            v["is_active"] = False

        # Activate the second-to-last version
        previous_version = skill_versions[-2]
        previous_version["is_active"] = True

        return {
            **previous_version,
            "rolled_back_at": datetime.now(timezone.utc).isoformat(),
        }

    async def get_version_history(
        self,
        skill_id: uuid.UUID,
        company_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Get all versions of a skill.

        Args:
            skill_id: The skill to get history for.
            company_id: The company owning the skill.

        Returns:
            List of all version records sorted by version number.
        """
        versions = [
            v for v in self._versions
            if v["skill_id"] == str(skill_id) and v["company_id"] == str(company_id)
        ]
        versions.sort(key=lambda v: v["version_number"])
        return versions
