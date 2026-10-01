"""governance studio: policy versions, drafts, temporary access, restrictions

Revision ID: e7a1c2d3f408
Revises: f1b7c9d2a508
Create Date: 2026-09-30

Five tenant tables, each with ``company_id`` and the same FORCE ``tenant_isolation``
row-level security as the other tenant tables (PostgreSQL only; SQLite skips it).
``(company_id, version_number)`` is unique so concurrent publishes cannot both win.
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel

from alembic import op

revision: str = "e7a1c2d3f408"
down_revision: str | None = "f1b7c9d2a508"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "governance_policy_versions",
    "governance_policy_drafts",
    "governance_temp_access",
    "governance_restrictions",
    "governance_grant_uses",
)
_TENANT_PREDICATE = "company_id = NULLIF(current_setting('nexus.company_id', true), '')::uuid"


def _s(n: int) -> sqlmodel.sql.sqltypes.AutoString:
    return sqlmodel.sql.sqltypes.AutoString(length=n)


def upgrade() -> None:
    uid = sa.Uuid()
    op.create_table(
        "governance_policy_versions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", _s(30), nullable=False),
        sa.Column("rules_snapshot", sa.JSON(), nullable=True),
        sa.Column("base_version", sa.Integer(), nullable=True),
        sa.Column("published_by", _s(255), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("rollback_of", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("company_id", "version_number"),
    )
    op.create_index(
        "ix_governance_policy_versions_company_id", "governance_policy_versions", ["company_id"]
    )
    op.create_table(
        "governance_policy_drafts",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("proposed_rules", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("ticket_ref", _s(255), nullable=True),
        sa.Column("created_by", _s(255), nullable=False),
        sa.Column("reviewers", sa.JSON(), nullable=True),
        sa.Column("status", _s(30), nullable=False),
        sa.Column("published_version", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_governance_policy_drafts_company_id", "governance_policy_drafts", ["company_id"]
    )
    op.create_index("ix_governance_policy_drafts_status", "governance_policy_drafts", ["status"])
    op.create_table(
        "governance_temp_access",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("agent_id", uid, sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("effect", _s(10), nullable=False),
        sa.Column("tool_name", _s(255), nullable=False),
        sa.Column("risk_level", _s(30), nullable=False),
        sa.Column("status", _s(30), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=True),
        sa.Column("used_count", sa.Integer(), nullable=False),
        sa.Column("session_id", uid, nullable=True),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("requested_by", _s(255), nullable=False),
        sa.Column("approved_by", _s(255), nullable=True),
        sa.Column("approval_id", uid, nullable=True),
        sa.Column("revoked_by", _s(255), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ("company_id", "agent_id", "status", "approval_id"):
        op.create_index(f"ix_governance_temp_access_{col}", "governance_temp_access", [col])
    op.create_table(
        "governance_restrictions",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("scope", _s(20), nullable=False),
        sa.Column("agent_id", uid, sa.ForeignKey("agents.id"), nullable=True),
        sa.Column("kind", _s(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("created_by", _s(255), nullable=False),
        sa.Column("released_by", _s(255), nullable=True),
        sa.Column("released_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for col in ("company_id", "agent_id", "active"):
        op.create_index(f"ix_governance_restrictions_{col}", "governance_restrictions", [col])

    op.create_table(
        "governance_grant_uses",
        sa.Column("id", uid, primary_key=True),
        sa.Column("company_id", uid, sa.ForeignKey("companies.id"), nullable=False),
        sa.Column("grant_id", uid, sa.ForeignKey("governance_temp_access.id"), nullable=False),
        sa.Column("invocation_key", _s(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("grant_id", "invocation_key"),
    )
    for col in ("company_id", "grant_id"):
        op.create_index(f"ix_governance_grant_uses_{col}", "governance_grant_uses", [col])

    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING ({_TENANT_PREDICATE}) WITH CHECK ({_TENANT_PREDICATE});"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in _TABLES:
            op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table};")
    for table in reversed(_TABLES):
        op.drop_table(table)
