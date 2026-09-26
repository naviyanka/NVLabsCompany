"""Confine server-side filesystem paths to per-tenant roots.

A path a caller supplies (or one stored on a row a caller could once write) is
only trusted once it resolves inside one of the configured roots.
``resolve()`` collapses ``..`` and follows symlinks and Windows junctions
before the containment check, so neither can escape a root.
"""

import uuid
from pathlib import Path


def resolve_in_roots(raw: str, roots: str, company_id: uuid.UUID) -> Path | None:
    """Resolve ``raw`` and return it if it lies inside one of ``roots``, else None.

    Args:
        raw: The path to check.
        roots: Comma-separated root directories; ``{company_id}`` is substituted
            with the tenant's id, so one tenant's root never contains another's.
        company_id: The tenant the path must belong to.
    """
    path = Path(raw).expanduser().resolve()
    for root in roots.split(","):
        root = root.strip()
        if not root:
            continue
        root_path = Path(root.replace("{company_id}", str(company_id))).expanduser().resolve()
        if path.is_relative_to(root_path):
            return path
    return None
