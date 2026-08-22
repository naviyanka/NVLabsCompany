"""add auth columns and invites

Adds everything the authentication layer needs to existing tables, and creates
the invite table. Three concerns are handled here:

1. ``user_profiles`` becomes the fastapi-users user table. It gains
   ``hashed_password`` and the ``is_active`` / ``is_superuser`` / ``is_verified``
   flags required by ``UserProtocol``, plus ``last_login_at``. Its email index
   becomes unique.

   Before that index can be created, existing duplicate emails must go. Earlier
   versions of ``GET /api/v1/profile`` fabricated a profile row per company,
   all using the same ``admin@nvlabs.company`` address, so a database that
   served more than one company almost certainly holds duplicates. Rather than
   delete those rows (``user_sessions`` references them), every duplicate after
   the first is rewritten to a unique ``dup+<id>@invalid.local`` address. The
   operator can then reassign real addresses. The comparison is
   case-insensitive, which is stricter than the resulting index; application
   code lowercases email on write.

2. ``user_sessions`` gains ``token_hash`` (the SHA-256 of the opaque cookie
   value, uniquely indexed) plus ``expires_at`` and ``revoked_at``. Rows that
   predate this migration have no token and can never authenticate anything,
   but they are kept for their audit value: each is backfilled with a
   placeholder derived from its own id, which is unique and, being 32 hex
   characters rather than 64, cannot collide with any real SHA-256 hash.

3. ``api_keys`` gains ``role`` (a key may carry less authority than its
   creator) and ``created_by``, and its ``key_hash`` gains an index because
   every authenticated request now looks a key up by hash.

Revision ID: b7d3c9e14f20
Revises: 1e101df7eda6
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b7d3c9e14f20'
down_revision: Union[str, None] = '1e101df7eda6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Keeps the earliest row per address and pushes every later one to a unique
# placeholder. CAST(... AS TEXT) rather than ::text so this runs on SQLite too.
_DEDUPE_EMAILS = sa.text(
    """
    UPDATE user_profiles
       SET email = 'dup+' || CAST(id AS TEXT) || '@invalid.local'
     WHERE id IN (
           SELECT id FROM (
                  SELECT id,
                         ROW_NUMBER() OVER (
                             PARTITION BY lower(email)
                             ORDER BY created_at, CAST(id AS TEXT)
                         ) AS rn
                    FROM user_profiles
           ) ranked
            WHERE rn > 1
     )
    """
)

_BACKFILL_SESSION_TOKENS = sa.text(
    """
    UPDATE user_sessions
       SET token_hash = REPLACE(CAST(id AS TEXT), '-', '')
     WHERE token_hash = '' OR token_hash IS NULL
    """
)


def upgrade() -> None:
    # --- user_profiles: fastapi-users protocol columns ---
    op.add_column(
        'user_profiles',
        sa.Column(
            'hashed_password',
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
            server_default='',
        ),
    )
    op.add_column(
        'user_profiles',
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        'user_profiles',
        sa.Column('is_superuser', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'user_profiles',
        sa.Column('is_verified', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column('user_profiles', sa.Column('last_login_at', sa.DateTime(), nullable=True))

    op.execute(_DEDUPE_EMAILS)
    op.drop_index(op.f('ix_user_profiles_email'), table_name='user_profiles')
    op.create_index(op.f('ix_user_profiles_email'), 'user_profiles', ['email'], unique=True)

    # --- user_sessions: hashed opaque token + lifecycle ---
    op.add_column(
        'user_sessions',
        sa.Column(
            'token_hash',
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
            server_default='',
        ),
    )
    op.add_column('user_sessions', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.add_column('user_sessions', sa.Column('revoked_at', sa.DateTime(), nullable=True))
    op.execute(_BACKFILL_SESSION_TOKENS)
    op.create_index(
        op.f('ix_user_sessions_token_hash'), 'user_sessions', ['token_hash'], unique=True
    )

    # --- api_keys: service principal role + provenance ---
    op.add_column(
        'api_keys',
        sa.Column(
            'role',
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default='viewer',
        ),
    )
    op.add_column('api_keys', sa.Column('created_by', sa.Uuid(), nullable=True))
    # SQLite cannot ALTER TABLE ADD CONSTRAINT. Dev runs on SQLite via
    # create_all(), which builds the constraint from the model, so skipping it
    # here costs nothing there and keeps Postgres fully constrained.
    if op.get_bind().dialect.name != 'sqlite':
        op.create_foreign_key(
            'fk_api_keys_created_by_user_profiles',
            'api_keys',
            'user_profiles',
            ['created_by'],
            ['id'],
        )
    op.create_index(op.f('ix_api_keys_key_hash'), 'api_keys', ['key_hash'], unique=False)

    # --- auth_invites: invite-only onboarding ---
    op.create_table(
        'auth_invites',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column('email', sqlmodel.sql.sqltypes.AutoString(length=255), nullable=False),
        sa.Column('role', sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False),
        sa.Column('token_hash', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('accepted_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ),
        sa.ForeignKeyConstraint(['created_by'], ['user_profiles.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_auth_invites_company_id'), 'auth_invites', ['company_id'], unique=False
    )
    op.create_index(op.f('ix_auth_invites_email'), 'auth_invites', ['email'], unique=False)
    op.create_index(
        op.f('ix_auth_invites_token_hash'), 'auth_invites', ['token_hash'], unique=True
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_auth_invites_token_hash'), table_name='auth_invites')
    op.drop_index(op.f('ix_auth_invites_email'), table_name='auth_invites')
    op.drop_index(op.f('ix_auth_invites_company_id'), table_name='auth_invites')
    op.drop_table('auth_invites')

    op.drop_index(op.f('ix_api_keys_key_hash'), table_name='api_keys')
    if op.get_bind().dialect.name != 'sqlite':
        op.drop_constraint('fk_api_keys_created_by_user_profiles', 'api_keys', type_='foreignkey')
    op.drop_column('api_keys', 'created_by')
    op.drop_column('api_keys', 'role')

    op.drop_index(op.f('ix_user_sessions_token_hash'), table_name='user_sessions')
    op.drop_column('user_sessions', 'revoked_at')
    op.drop_column('user_sessions', 'expires_at')
    op.drop_column('user_sessions', 'token_hash')

    op.drop_index(op.f('ix_user_profiles_email'), table_name='user_profiles')
    op.create_index(op.f('ix_user_profiles_email'), 'user_profiles', ['email'], unique=False)
    op.drop_column('user_profiles', 'last_login_at')
    op.drop_column('user_profiles', 'is_verified')
    op.drop_column('user_profiles', 'is_superuser')
    op.drop_column('user_profiles', 'is_active')
    op.drop_column('user_profiles', 'hashed_password')
