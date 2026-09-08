"""add cryptographic multi-party approval signing

Ed25519 signer keys plus verified signatures over an approval's canonical bytes,
and a per-approval quorum count. Existing approvals keep required_signatures=1,
so every pre-existing flow behaves exactly as it did.

Revision ID: b6f3d1a72e60
Revises: a4e2c8b91f50
Create Date: 2026-08-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic
revision: str = "b6f3d1a72e60"
down_revision: Union[str, None] = "a4e2c8b91f50"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "approvals",
        sa.Column(
            "required_signatures", sa.Integer(), nullable=False, server_default="1"
        ),
    )

    op.create_table(
        "approval_signer_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "company_id",
            sa.Uuid(),
            sa.ForeignKey("companies.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("subject", sa.String(length=255), nullable=False, index=True),
        sa.Column("public_key", sa.String(length=128), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "approval_signatures",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "approval_id",
            sa.Uuid(),
            sa.ForeignKey("approvals.id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "signer_key_id",
            sa.Uuid(),
            sa.ForeignKey("approval_signer_keys.id"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column(
            "signed_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # One signature per party per approval: without this, one operator
        # signing twice would satisfy a two-party quorum alone.
        sa.UniqueConstraint(
            "approval_id", "subject", name="uq_approval_signature_subject"
        ),
    )


def downgrade() -> None:
    op.drop_table("approval_signatures")
    op.drop_table("approval_signer_keys")
    op.drop_column("approvals", "required_signatures")
