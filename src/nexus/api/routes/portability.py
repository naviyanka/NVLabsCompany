"""Company export/import endpoints — portable, secret-scrubbed archives.

Thin HTTP surface over `CompanyPortabilityService`. Export walks the company's
full graph and scrubs secret columns (recording what it removed); import mints
fresh UUIDs and rewrites references so an archive can be cloned into a new
company.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from nexus.api.deps import DbSession, PathCompanyId, RequireAdmin
from nexus.services.portability_service import CompanyPortabilityService

router = APIRouter(tags=["portability"])


class CompanyImportRequest(BaseModel):
    """Request body for importing a company archive."""

    archive: dict[str, Any]
    new_name: str | None = None


@router.get("/api/v1/companies/{company_id}/export")
async def export_company(
    company_id: PathCompanyId, db: DbSession, principal: RequireAdmin
) -> dict[str, Any]:
    """Export the company's full graph as a secret-scrubbed JSON archive."""
    service = CompanyPortabilityService(db)
    try:
        return await service.export_company(company_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/companies/import")
async def import_company(
    body: CompanyImportRequest, db: DbSession, principal: RequireAdmin
) -> dict[str, Any]:
    """Import a company archive into a fresh company with remapped IDs."""
    if not body.archive or "tables" not in body.archive:
        raise HTTPException(status_code=400, detail="archive is missing 'tables'")

    service = CompanyPortabilityService(db)
    try:
        new_id: uuid.UUID = await service.import_company(body.archive, new_name=body.new_name)
        await db.commit()
    except (ValueError, KeyError) as exc:
        await db.rollback()
        raise HTTPException(status_code=400, detail=f"invalid archive: {exc}") from exc
    except IntegrityError as exc:
        await db.rollback()
        # A globally-unique value (e.g. a user email) already exists. This
        # happens when cloning into a DB that already holds the source rows;
        # the archive imports cleanly into a fresh database.
        raise HTTPException(
            status_code=409,
            detail=(
                "Import conflicts with existing data (a unique value such as a "
                "user email already exists). Company archives import cleanly "
                "into a fresh database; cloning within the same database is not "
                "supported for rows with global unique constraints."
            ),
        ) from exc
    manifest = body.archive.get("manifest", {})
    return {
        "company_id": str(new_id),
        "source_company_id": manifest.get("company_id"),
        "new_name": body.new_name or manifest.get("company_name"),
    }
