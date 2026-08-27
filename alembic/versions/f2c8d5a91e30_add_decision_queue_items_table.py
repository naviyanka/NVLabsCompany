"""add_decision_queue_items_table

Phase 0.2 — persist decision-queue triage state so approvals and pending
decisions survive a restart instead of living in DecisionQueueManager._queues.

Revision ID: f2c8d5a91e30
Revises: e1a7b4c93d20
Create Date: 2026-08-26 22:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = "f2c8d5a91e30"
down_revision: Union[str, None] = "e1a7b4c93d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_queue_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("queue_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source_kind",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "status", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.Column(
            "decision_outcome",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=True,
        ),
        sa.Column("decide_by", sa.DateTime(), nullable=True),
        sa.Column("snoozed_until", sa.DateTime(), nullable=True),
        sa.Column("needs_notification", sa.Boolean(), nullable=False),
        sa.Column("notification_delivered", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["queue_id"], ["decision_queues.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_decision_queue_items_queue_id"),
        "decision_queue_items",
        ["queue_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_queue_items_company_id"),
        "decision_queue_items",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_queue_items_decision_id"),
        "decision_queue_items",
        ["decision_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_queue_items_status"),
        "decision_queue_items",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_decision_queue_items_priority"),
        "decision_queue_items",
        ["priority"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_decision_queue_items_priority"),
        table_name="decision_queue_items",
    )
    op.drop_index(
        op.f("ix_decision_queue_items_status"),
        table_name="decision_queue_items",
    )
    op.drop_index(
        op.f("ix_decision_queue_items_decision_id"),
        table_name="decision_queue_items",
    )
    op.drop_index(
        op.f("ix_decision_queue_items_company_id"),
        table_name="decision_queue_items",
    )
    op.drop_index(
        op.f("ix_decision_queue_items_queue_id"),
        table_name="decision_queue_items",
    )
    op.drop_table("decision_queue_items")
