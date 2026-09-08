"""Obsidian integration endpoints — operator-facing status and scan.

Thin HTTP surface over `ObsidianVaultService`. The route is an adapter: it maps
the authenticated company onto the service, turns vault errors into status codes,
and shapes the response. Every scanning decision — filesystem access, identity,
reconciliation, hashing, security — belongs to `VaultScanner`.

Read-only with respect to the vault (ADR 0002 §23). These endpoints update
`obsidian_documents`, which is the reconciliation registry, and never touch a
`.md` file, its frontmatter, a directory, or Git state.
"""

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Optional, TypeVar

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.obsidian.security import VaultNotConfiguredError
from nexus.services.obsidian_service import (
    ObsidianVaultService,
    ScanInProgressError,
    VaultUnavailableError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["obsidian"])

_T = TypeVar("_T")


class VaultStatusResponse(BaseModel):
    """Whether the Obsidian integration is usable for this company.

    The absolute vault root is deliberately absent: it is host filesystem
    layout, and a caller has no use for it.
    """

    # The company this answer is scoped to, echoed back so a caller can address
    # company-scoped routes without tracking it separately. Not a disclosure: it
    # is the caller's own company, taken from their credential.
    company_id: uuid.UUID
    state: str  # not_configured | available | unavailable
    configured: bool
    vault_present: bool
    indexed_documents: int
    detail: Optional[str] = None


class ScanCounts(BaseModel):
    """Per-classification totals for one scan."""

    seen: int
    created: int
    updated: int
    unchanged: int
    moved: int
    deleted: int
    skipped: int


class SkippedNote(BaseModel):
    """A note the scan could not read, and why."""

    vault_path: str
    reason: str


class ScanResponse(BaseModel):
    """Result of one vault scan.

    Paths are vault-relative, which is what the caller authored and already
    knows; no absolute host path is disclosed.
    """

    counts: ScanCounts
    created: list[str]
    updated: list[str]
    unchanged: list[str]
    moved: list[str]
    deleted: list[str]
    skipped: list[SkippedNote]


class IndexCounts(BaseModel):
    """Per-outcome totals for one indexing pass."""

    indexed: int
    partial: int
    failed: int
    skipped: int
    chunks_written: int


class FailedNote(BaseModel):
    """A note that could not be indexed, and why."""

    vault_path: str
    reason: str


class IndexAcceptedResponse(BaseModel):
    """A durable index run was submitted; it has not finished yet.

    Returned with 202 when Temporal is enabled. Counts are deliberately absent
    rather than zero: the run is in flight, and reporting zeros would claim a
    result that does not exist. Poll the workflow, or `GET /status` for the
    registry's own view.
    """

    mode: str = "durable"
    workflow_id: str
    task_queue: str
    detail: str


class IndexProgressResponse(BaseModel):
    """How far a durable index run has got.

    Counts come from the workflow itself and execution state from Temporal, which
    stays the single source of truth for both — `obsidian_documents` remains the
    source of truth for per-document index state, and `GET /status` is the way to
    read that.

    Counts are absent once a run has closed: a finished execution has no query
    handler left to answer, and reporting zeros for a completed run would be a
    lie. `state` is always present.
    """

    workflow_id: str
    state: str
    documents_total: Optional[int] = None
    documents_seen: Optional[int] = None
    remaining: Optional[int] = None
    chunks_written: Optional[int] = None
    indexed: Optional[int] = None
    partial: Optional[int] = None
    skipped: Optional[int] = None
    failed: Optional[int] = None


class IndexResponse(BaseModel):
    """Result of one indexing pass.

    ``partial`` means the note's text is searchable but its embedding vectors
    were not stored — retrieval falls back to keyword matching for it. It is
    reported separately from ``indexed`` precisely so that degradation is
    visible rather than silent (ADR 0002 §21).
    """

    counts: IndexCounts
    indexed: list[str]
    partial: list[str]
    skipped: list[str]
    failed: list[FailedNote]


async def _run_vault_operation(
    db: AsyncSession,
    company_id: uuid.UUID,
    operation: str,
    run: Callable[[], Awaitable[_T]],
) -> _T:
    """Run one vault operation, committing on success and rolling back on failure.

    Shared by scan and index: both preserve the same transaction contract — the
    service flushes but never commits, so nothing the operation wrote survives a
    failure — and both map the same service errors onto the same status codes.

    Args:
        db: The request's session.
        company_id: The authenticated company, for the log line only.
        operation: Verb used in client-facing detail and log messages.
        run: Zero-argument coroutine function performing the operation.

    Returns:
        Whatever ``run`` returned.

    Raises:
        HTTPException: 409 when the integration is unconfigured or a sibling
            operation is in flight, 503 when the vault cannot be read, 500 for
            anything unexpected. No filesystem detail reaches the client.
    """
    try:
        result = await run()
        await db.commit()
        return result
    except VaultNotConfiguredError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The Obsidian integration is not configured on this server.",
        ) from exc
    except ScanInProgressError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A vault operation is already running for this company.",
        ) from exc
    except VaultUnavailableError as exc:
        await db.rollback()
        # The service already logged the cause; the client gets no filesystem
        # detail.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        await db.rollback()
        logger.exception(
            "Obsidian vault %s failed for company %s", operation, company_id
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"The vault {operation} failed. Check the server logs.",
        ) from exc


@router.get(
    "/api/v1/integrations/obsidian/status",
    response_model=VaultStatusResponse,
)
async def get_obsidian_status(
    db: DbSession, company_id: CurrentCompanyId
) -> VaultStatusResponse:
    """Report the integration's state for the authenticated company.

    Cheap by design — it counts registry rows and stats one directory rather
    than walking the vault, so it is safe to poll.
    """
    vault_status = await ObsidianVaultService(db, company_id).status()
    return VaultStatusResponse(
        company_id=company_id,
        state=vault_status.state,
        configured=vault_status.configured,
        vault_present=vault_status.vault_present,
        indexed_documents=vault_status.indexed_documents,
        detail=vault_status.detail,
    )


@router.post(
    "/api/v1/integrations/obsidian/scan",
    response_model=ScanResponse,
)
async def scan_obsidian_vault(
    db: DbSession, company_id: CurrentCompanyId
) -> ScanResponse:
    """Reconcile the vault against `obsidian_documents` for this company.

    Takes no request body: the company comes from the authenticated principal,
    and the vault root from server configuration, so a caller cannot point a scan
    at another tenant or another directory.

    Commits only on success. A failed scan rolls back, so the registry never
    describes a vault state that did not exist.
    """
    service = ObsidianVaultService(db, company_id)
    result = await _run_vault_operation(db, company_id, "scan", service.scan)

    return ScanResponse(
        counts=ScanCounts(**result.counts()),
        created=result.created,
        updated=result.updated,
        unchanged=result.unchanged,
        moved=result.moved,
        deleted=result.deleted,
        skipped=[
            SkippedNote(vault_path=path, reason=reason) for path, reason in result.skipped
        ],
    )


@router.post(
    "/api/v1/integrations/obsidian/index",
    responses={
        200: {
            "model": IndexResponse,
            "description": "Indexed synchronously; counts are the finished result.",
        },
        202: {
            "model": IndexAcceptedResponse,
            "description": "Durable run submitted to Temporal; not yet finished.",
        },
    },
)
async def index_obsidian_vault(
    db: DbSession,
    company_id: CurrentCompanyId,
    # Annotated rather than `= Query(...)`: the latter makes the Query object
    # itself the function default, so a direct call (a test, or another service
    # reusing the handler) receives that object where an int was expected.
    limit: Annotated[
        Optional[int],
        Query(
            ge=1,
            le=1000,
            description=(
                "Cap on documents processed in this pass. Omit to index every "
                "stale document; set it to run a large first index in batches."
            ),
        ),
    ] = None,
) -> Any:
    """Chunk and embed the documents a scan left stale, for this company.

    Runs after `POST /scan`: the scan decides *which* notes need work by marking
    them stale, and this indexes those. Indexing a vault that has never been
    scanned finds nothing to do, which is the honest answer rather than an error.

    **One writer, two runners.** With `USE_TEMPORAL=true` this submits a durable
    workflow and answers 202 with its id; the workflow's activities then own every
    `obsidian_documents` write. With Temporal off it indexes inline and answers 200
    with the finished counts. What it never does is both: the request either hands
    the work to the workflow or does it itself, so the two cannot race over the
    same rows — the single-path invariant ADR 0001 exists to protect.

    Concurrency is enforced accordingly: Temporal rejects a second run for the
    same company by workflow id, and the synchronous path uses the in-process
    per-company lock. Either way a second caller gets 409.

    Read-only with respect to the vault: notes are read, never written.
    """
    from nexus.temporal.client import (
        TASK_QUEUE,
        ObsidianIndexAlreadyRunningError,
        start_obsidian_index_workflow,
    )

    try:
        workflow_id = await start_obsidian_index_workflow(str(company_id), limit=limit)
    except ObsidianIndexAlreadyRunningError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A vault operation is already running for this company.",
        ) from exc

    if workflow_id is not None:
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content=IndexAcceptedResponse(
                workflow_id=workflow_id,
                task_queue=TASK_QUEUE,
                detail=(
                    "Durable index run submitted. Counts are omitted because the "
                    "run has not finished; poll the workflow for its result."
                ),
            ).model_dump(),
        )

    # Temporal disabled or unreachable: index inline, exactly as before.
    service = ObsidianVaultService(db, company_id)
    result = await _run_vault_operation(
        db, company_id, "index", lambda: service.index(limit=limit)
    )

    return IndexResponse(
        counts=IndexCounts(**result.counts()),
        indexed=result.indexed,
        partial=result.partial,
        skipped=result.skipped,
        failed=[
            FailedNote(vault_path=path, reason=reason) for path, reason in result.failed
        ],
    )


@router.get(
    "/api/v1/integrations/obsidian/index/{workflow_id}",
    response_model=IndexProgressResponse,
)
async def get_obsidian_index_progress(
    company_id: CurrentCompanyId, workflow_id: str
) -> IndexProgressResponse:
    """Progress of the durable index run `POST /index` returned an id for.

    Closes the loop on the 202: the caller is handed a `workflow_id` and this is
    how they ask what became of it.

    The company comes from the authenticated principal, never from the request, and
    the run id is per company — so a caller asking about another tenant's workflow
    gets 404, the same answer as for an id that never existed. Nothing about
    another company's run is distinguishable from here.

    404 rather than 409 when Temporal is off: with `USE_TEMPORAL != true` indexing
    is synchronous and finishes inside the request, so there is no run to poll and
    no id was ever issued.
    """
    from nexus.temporal.client import (
        ObsidianIndexNotFoundError,
        ObsidianIndexUnavailableError,
        query_obsidian_index_progress,
    )

    try:
        progress = await query_obsidian_index_progress(str(company_id), workflow_id)
    except ObsidianIndexNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such index run for this company.",
        ) from exc
    except ObsidianIndexUnavailableError as exc:
        logger.warning(
            "Obsidian index progress unavailable for company %s: %s", company_id, exc
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such index run for this company.",
        ) from exc

    return IndexProgressResponse(**progress)
