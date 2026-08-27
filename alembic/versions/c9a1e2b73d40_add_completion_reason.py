"""add completion_reason to goals and tasks

Phase 1.1 — explicit completion-reason taxonomy. Values come from
``nexus.models.task.RunCompletionReason``; stored as a plain string so adding
a reason needs no migration and no DB-level enum surgery.

Revision ID: c9a1e2b73d40
Revises: f2c8d5a91e30
Create Date: 2026-08-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "c9a1e2b73d40"
down_revision: Union[str, None] = "f2c8d5a91e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table in ("goals", "tasks"):
        op.add_column(
            table, sa.Column("completion_reason", sa.String(length=32), nullable=True)
        )
        op.create_index(
            f"ix_{table}_completion_reason", table, ["completion_reason"], unique=False
        )

    # tasks.goal_id: the orchestrator queried a Task.parent_id that never existed
    # on the tasks table (parent_task_id points at another task, not a goal), so
    # every goal drive raised AttributeError before reaching a terminal path.
    # No FK constraint: SQLite cannot ALTER one in, and the index is what the
    # orchestrator's subtask lookup actually needs.
    op.add_column("tasks", sa.Column("goal_id", sa.Uuid(), nullable=True))
    op.create_index("ix_tasks_goal_id", "tasks", ["goal_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_goal_id", table_name="tasks")
    op.drop_column("tasks", "goal_id")

    for table in ("goals", "tasks"):
        op.drop_index(f"ix_{table}_completion_reason", table_name=table)
        op.drop_column(table, "completion_reason")
