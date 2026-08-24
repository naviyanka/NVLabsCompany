"""add chat_messages table

Revision ID: f08ae95d1234
Revises: cb75b52327c0
Create Date: 2026-08-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic
revision: str = "f08ae95d1234"
down_revision: Union[str, None] = "cb75b52327c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("sender", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("model_used", sa.String(length=100), nullable=True),
        sa.Column("tokens_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_chat_messages_company_id", "chat_messages", ["company_id"])
    op.create_index("ix_chat_messages_agent_id", "chat_messages", ["agent_id"])
    op.create_index("ix_chat_messages_conversation_id", "chat_messages", ["conversation_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_conversation_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_agent_id", table_name="chat_messages")
    op.drop_index("ix_chat_messages_company_id", table_name="chat_messages")
    op.drop_table("chat_messages")
