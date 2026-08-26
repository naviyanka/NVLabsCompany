"""add hr training curricula and performance reviews tables

Revision ID: c7d9e1f4a520
Revises: b5e8f3a72c10
Create Date: 2026-08-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "c7d9e1f4a520"
down_revision: Union[str, None] = "b5e8f3a72c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "hr_training_curricula",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("benchmark_lift", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["target_agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hr_training_curricula_company_id", "hr_training_curricula", ["company_id"]
    )
    op.create_index(
        "ix_hr_training_curricula_target_agent_id",
        "hr_training_curricula",
        ["target_agent_id"],
    )

    op.create_table(
        "hr_performance_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("review_type", sa.String(length=50), nullable=False),
        sa.Column("feedback", sa.String(length=4000), nullable=False),
        sa.Column("author", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_hr_performance_reviews_company_id", "hr_performance_reviews", ["company_id"]
    )
    op.create_index(
        "ix_hr_performance_reviews_agent_id", "hr_performance_reviews", ["agent_id"]
    )
    op.create_index(
        "ix_hr_performance_reviews_created_at", "hr_performance_reviews", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_hr_performance_reviews_created_at", table_name="hr_performance_reviews"
    )
    op.drop_index(
        "ix_hr_performance_reviews_agent_id", table_name="hr_performance_reviews"
    )
    op.drop_index(
        "ix_hr_performance_reviews_company_id", table_name="hr_performance_reviews"
    )
    op.drop_table("hr_performance_reviews")
    op.drop_index(
        "ix_hr_training_curricula_target_agent_id", table_name="hr_training_curricula"
    )
    op.drop_index(
        "ix_hr_training_curricula_company_id", table_name="hr_training_curricula"
    )
    op.drop_table("hr_training_curricula")
