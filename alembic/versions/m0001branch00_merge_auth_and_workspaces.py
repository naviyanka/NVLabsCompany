"""merge auth and workspaces branches

Revision ID: m0001branch00
Revises: b7d3c9e14f20, dd22d28a5678
Create Date: 2026-08-26

The api-keys/auth-columns branch (1e101df7eda6 -> b7d3c9e14f20) and the
workspaces branch (cb75b52327c0 -> f08ae95d1234 -> dd22d28a5678) were authored
in parallel off cb75b52327c0 and never merged, leaving two heads — which makes
`alembic upgrade head` fail. This empty revision joins them.
"""

from typing import Sequence, Union

# revision identifiers, used by Alembic
revision: str = "m0001branch00"
down_revision: Union[str, None] = ("b7d3c9e14f20", "dd22d28a5678")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
