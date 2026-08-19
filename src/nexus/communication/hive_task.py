"""Hive Task - kanban-style task ledger for agent coordination."""

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Status of a task in the hive ledger."""

    TODO = "todo"
    DOING = "doing"
    BLOCKED = "blocked"
    DONE = "done"


class HiveTask(BaseModel):
    """A task in the hive's kanban ledger."""

    id: str
    title: str
    description: Optional[str] = None
    assignee: Optional[str] = None
    status: TaskStatus = TaskStatus.TODO
    depends_on: list[str] = Field(default_factory=list)
    priority: int = 0
    human_qa: list[dict] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
