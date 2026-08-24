"""OKR (Objectives and Key Results) Management System.

Provides structured objective tracking with key results, progress
computation, and risk detection for the autonomous company.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any, Optional


@dataclass
class KeyResult:
    """A measurable key result contributing to an objective.

    Attributes:
        id: Unique identifier for this key result.
        objective_id: UUID of the parent objective.
        title: Short description of the key result.
        target_value: The target numeric value to achieve.
        current_value: The current progress value (default 0.0).
        unit: Unit of measurement (e.g., 'percent', 'count', 'dollars').
        status: Current status - 'on_track', 'at_risk', or 'behind'.
        updated_at: Timestamp of last progress update.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    objective_id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""
    target_value: float = 100.0
    current_value: float = 0.0
    unit: str = "percent"
    status: str = "on_track"
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class Objective:
    """A strategic objective with associated key results.

    Attributes:
        id: Unique identifier for this objective.
        title: Short title of the objective.
        description: Detailed description of what this objective achieves.
        owner_agent_id: UUID of the agent responsible for this objective.
        time_frame: Time frame for completion (e.g., 'Q1 2025', '30 days').
        status: Current status - 'active', 'completed', or 'cancelled'.
        key_results: List of associated KeyResult instances.
        created_at: Timestamp of objective creation.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    title: str = ""
    description: str = ""
    owner_agent_id: uuid.UUID = field(default_factory=uuid.uuid4)
    time_frame: str = "Q1 2025"
    status: str = "active"
    key_results: list[KeyResult] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


import json
from pathlib import Path

_OKR_FILE = Path("data/okrs_database.json")


class OKRManager:
    """Manages objectives and key results for the company.

    Provides CRUD operations, progress computation, and risk detection
    for objectives and their associated key results. Uses in-memory
    storage with persistent JSON database backing.

    Attributes:
        objectives: Dictionary mapping objective IDs to Objective instances.
        company_id: The company this manager operates within.
    """

    def __init__(self, company_id: uuid.UUID | None = None, db: Any = None) -> None:
        """Initialize the OKR manager.

        Args:
            company_id: Optional company UUID for scoping.
            db: Optional database session for persistence.
        """
        self._company_id = company_id
        self._db = db
        self._objectives: dict[uuid.UUID, Objective] = {}
        self._load_from_file()

    def _load_from_file(self) -> None:
        if _OKR_FILE.exists():
            try:
                raw_data = json.loads(_OKR_FILE.read_text(encoding="utf-8"))
                for obj_dict in raw_data:
                    krs = [
                        KeyResult(
                            id=uuid.UUID(kr["id"]),
                            objective_id=uuid.UUID(kr["objective_id"]),
                            title=kr["title"],
                            target_value=kr["target_value"],
                            current_value=kr.get("current_value", 0.0),
                            unit=kr.get("unit", "percent"),
                            status=kr.get("status", "on_track"),
                        )
                        for kr in obj_dict.get("key_results", [])
                    ]
                    obj = Objective(
                        id=uuid.UUID(obj_dict["id"]),
                        title=obj_dict["title"],
                        description=obj_dict.get("description", ""),
                        owner_agent_id=uuid.UUID(obj_dict["owner_agent_id"]),
                        time_frame=obj_dict.get("time_frame", "Q1 2025"),
                        status=obj_dict.get("status", "active"),
                        key_results=krs,
                    )
                    self._objectives[obj.id] = obj
            except Exception:
                pass

    def _save_to_file(self) -> None:
        try:
            _OKR_FILE.parent.mkdir(parents=True, exist_ok=True)
            export_list = []
            for obj in self._objectives.values():
                export_list.append({
                    "id": str(obj.id),
                    "title": obj.title,
                    "description": obj.description,
                    "owner_agent_id": str(obj.owner_agent_id),
                    "time_frame": obj.time_frame,
                    "status": obj.status,
                    "key_results": [
                        {
                            "id": str(kr.id),
                            "objective_id": str(kr.objective_id),
                            "title": kr.title,
                            "target_value": kr.target_value,
                            "current_value": kr.current_value,
                            "unit": kr.unit,
                            "status": kr.status,
                        }
                        for kr in obj.key_results
                    ],
                })
            _OKR_FILE.write_text(json.dumps(export_list, indent=2), encoding="utf-8")
        except Exception:
            pass

    def create_objective(
        self,
        title: str,
        description: str,
        owner_agent_id: uuid.UUID,
        time_frame: str = "Q1 2025",
    ) -> Objective:
        """Create a new objective.

        Args:
            title: Short title of the objective.
            description: Detailed description.
            owner_agent_id: UUID of the responsible agent.
            time_frame: Time frame string (e.g., 'Q1 2025', '30 days').

        Returns:
            The newly created Objective instance.
        """
        objective = Objective(
            title=title,
            description=description,
            owner_agent_id=owner_agent_id,
            time_frame=time_frame,
            status="active",
        )
        self._objectives[objective.id] = objective
        self._save_to_file()
        return objective

    def add_key_result(
        self,
        objective_id: uuid.UUID,
        title: str,
        target_value: float,
        unit: str = "percent",
    ) -> KeyResult:
        """Add a key result to an existing objective.

        Args:
            objective_id: UUID of the parent objective.
            title: Short description of the key result.
            target_value: The numeric target to achieve.
            unit: Unit of measurement.

        Returns:
            The newly created KeyResult instance.

        Raises:
            KeyError: If the objective does not exist.
        """
        objective = self._objectives.get(objective_id)
        if objective is None:
            raise KeyError(f"Objective {objective_id} not found")

        key_result = KeyResult(
            objective_id=objective_id,
            title=title,
            target_value=target_value,
            current_value=0.0,
            unit=unit,
            status="on_track",
        )
        objective.key_results.append(key_result)
        self._save_to_file()
        return key_result

    def update_progress(
        self,
        key_result_id: uuid.UUID,
        current_value: float,
    ) -> KeyResult:
        """Update the progress of a key result.

        Args:
            key_result_id: UUID of the key result to update.
            current_value: The new current value.

        Returns:
            The updated KeyResult instance.

        Raises:
            KeyError: If the key result does not exist.
        """
        for objective in self._objectives.values():
            for kr in objective.key_results:
                if kr.id == key_result_id:
                    kr.current_value = current_value
                    kr.updated_at = datetime.now(UTC)

                    # Update status based on progress
                    progress = (
                        kr.current_value / kr.target_value
                        if kr.target_value > 0
                        else 0.0
                    )
                    if progress >= 0.7:
                        kr.status = "on_track"
                    elif progress >= 0.3:
                        kr.status = "at_risk"
                    else:
                        kr.status = "behind"

                    self._save_to_file()
                    return kr

        raise KeyError(f"KeyResult {key_result_id} not found")

    def get_company_okrs(self) -> list[Objective]:
        """Get all objectives for the company.

        Returns:
            List of all Objective instances managed by this OKRManager.
        """
        return list(self._objectives.values())

    def get_objective(self, objective_id: uuid.UUID) -> Optional[Objective]:
        """Get a single objective by ID.

        Args:
            objective_id: UUID of the objective to retrieve.

        Returns:
            The Objective instance, or None if not found.
        """
        return self._objectives.get(objective_id)

    def compute_objective_progress(self, objective_id: uuid.UUID) -> float:
        """Compute the overall progress of an objective.

        Calculates a weighted average of all key results' progress.
        Each key result has equal weight. Progress is the ratio of
        current_value to target_value, capped at 1.0.

        Args:
            objective_id: UUID of the objective.

        Returns:
            Float between 0.0 and 1.0 representing overall progress.

        Raises:
            KeyError: If the objective does not exist.
        """
        objective = self._objectives.get(objective_id)
        if objective is None:
            raise KeyError(f"Objective {objective_id} not found")

        if not objective.key_results:
            return 0.0

        total_progress = 0.0
        for kr in objective.key_results:
            if kr.target_value > 0:
                kr_progress = min(kr.current_value / kr.target_value, 1.0)
            else:
                kr_progress = 0.0
            total_progress += kr_progress

        return total_progress / len(objective.key_results)

    def detect_at_risk_objectives(
        self,
        time_elapsed_fraction: float = 0.7,
    ) -> list[Objective]:
        """Detect objectives that are at risk of not being met.

        An objective is considered at risk if any of its key results
        have less than 30% progress when more than 70% of the time
        frame has elapsed (configurable via time_elapsed_fraction).

        Args:
            time_elapsed_fraction: Fraction of time frame elapsed (0.0 to 1.0).
                Objectives are checked when this exceeds 0.7 by default.

        Returns:
            List of Objective instances that are at risk.
        """
        at_risk: list[Objective] = []

        if time_elapsed_fraction < 0.7:
            return at_risk

        for objective in self._objectives.values():
            if objective.status != "active":
                continue

            for kr in objective.key_results:
                if kr.target_value > 0:
                    progress = kr.current_value / kr.target_value
                else:
                    progress = 0.0

                if progress < 0.3:
                    at_risk.append(objective)
                    break  # Only add objective once

        return at_risk
