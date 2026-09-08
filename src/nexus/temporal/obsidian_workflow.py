"""Durable Obsidian vault indexing workflow (ADR 0002 §23, Phase 1C).

Orchestration only. The body holds no clock read, no UUID generation, no
filesystem access and no database session, because Temporal replays it: any of
those would make a replay diverge from the original run. Every side effect is an
activity (ADR 0001).

Shape:

    list pending documents  (one activity, retry-safe)
            │
            ▼
    for each document: index it  (one activity each, ONCE_ONLY)

One activity per document is what makes a large first index restartable. A worker
that dies takes one document's attempt with it; the workflow history already
records which documents finished, so a resumed run does not redo them.

``ONCE_ONLY`` on the indexing activity because embedding is billed per call
(ADR 0001). The application's own bounded retry — ``attempt_count`` on
``obsidian_documents``, from Phase 1B-3C — is what decides whether a failed
document is tried again, on a later pass rather than a Temporal retry. Two retry
mechanisms stacked on one billable operation would multiply the charge.
"""

from dataclasses import dataclass, field

from nexus.temporal._sdk import (
    DEFAULT_TIMEOUT,
    LLM_TIMEOUT,
    ONCE_ONLY,
    execute_activity,
    imports_passed_through,
    workflow_defn,
    workflow_query,
    workflow_run,
)

with imports_passed_through():
    from nexus.temporal.obsidian_activities import (
        OUTCOME_FAILED,
        OUTCOME_INDEXED,
        OUTCOME_PARTIAL,
        OUTCOME_SKIPPED,
        IndexDocumentInput,
        PendingDocumentsInput,
        index_obsidian_document_activity,
        list_pending_obsidian_documents_activity,
    )


@dataclass
class ObsidianIndexInput:
    """What to index.

    Attributes:
        company_id: The company whose vault is indexed, as a string because UUIDs
            do not survive the JSON boundary between workflow and activity.
        limit: Optional cap on documents in this run.
    """

    company_id: str
    limit: int | None = None


@dataclass
class ObsidianIndexOutput:
    """Per-outcome totals plus the vault paths behind them.

    Mirrors the synchronous ``IndexResult`` so an operator reading a workflow
    result and an operator reading an HTTP response see the same shape. Paths are
    vault-relative; ``failed`` carries a client-safe reason with no host path.
    """

    company_id: str
    documents_seen: int = 0
    chunks_written: int = 0
    indexed: list[str] = field(default_factory=list)
    partial: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    failure_reasons: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        """Flat summary, matching ``IndexResult.counts()``."""
        return {
            "indexed": len(self.indexed),
            "partial": len(self.partial),
            "failed": len(self.failed),
            "skipped": len(self.skipped),
            "chunks_written": self.chunks_written,
        }


@dataclass
class ObsidianIndexProgress:
    """How far the run has got, answered from workflow state.

    Counts only, no vault paths: a progress poll is a cheap "how far along" check,
    and the finished run's result already carries the paths. ``remaining`` is
    derived from the listing rather than stored separately, so it cannot disagree
    with what the run is actually working through.

    ``documents_total`` is 0 until the listing activity returns — that is the
    honest answer for a run that has not yet decided how much work there is,
    rather than a guess.
    """

    company_id: str
    documents_total: int = 0
    documents_seen: int = 0
    remaining: int = 0
    chunks_written: int = 0
    indexed: int = 0
    partial: int = 0
    skipped: int = 0
    failed: int = 0


@workflow_defn(name="ObsidianIndexWorkflow")
class ObsidianIndexWorkflow:
    """Indexes every document with pending work, one activity per document."""

    def __init__(self) -> None:
        # Progress state, kept on the instance so the query handler can answer
        # mid-run. Replay rebuilds it from the same history, so a query after a
        # worker restart reports the same numbers.
        self._output = ObsidianIndexOutput(company_id="")
        self._documents_total = 0

    @workflow_query
    def progress(self) -> ObsidianIndexProgress:
        """Counts so far, for a caller holding the workflow id.

        A query rather than a database read: Temporal owns execution progress,
        ``obsidian_documents`` owns per-document index state, and duplicating the
        first into a table would give an operator two numbers to reconcile. The
        handler only reads workflow state — a query must not mutate it or run an
        activity, because Temporal may run it during replay.
        """
        counts = self._output.counts()
        return ObsidianIndexProgress(
            company_id=self._output.company_id,
            documents_total=self._documents_total,
            documents_seen=self._output.documents_seen,
            remaining=max(0, self._documents_total - self._output.documents_seen),
            chunks_written=counts["chunks_written"],
            indexed=counts["indexed"],
            partial=counts["partial"],
            skipped=counts["skipped"],
            failed=counts["failed"],
        )

    @workflow_run
    async def run(self, input: ObsidianIndexInput) -> ObsidianIndexOutput:
        output = self._output
        output.company_id = input.company_id

        pending = await execute_activity(
            list_pending_obsidian_documents_activity,
            PendingDocumentsInput(company_id=input.company_id, limit=input.limit),
            timeout=DEFAULT_TIMEOUT,
        )
        self._documents_total = len(pending.nexus_ids)

        for nexus_id in pending.nexus_ids:
            result = await execute_activity(
                index_obsidian_document_activity,
                IndexDocumentInput(company_id=input.company_id, nexus_id=nexus_id),
                # Embedding can be a slow provider call, so it gets the same
                # generous ceiling as the LLM activities rather than the default.
                timeout=LLM_TIMEOUT,
                maximum_attempts=ONCE_ONLY,
            )

            output.documents_seen += 1
            output.chunks_written += result.chunks_written

            if result.outcome == OUTCOME_INDEXED:
                output.indexed.append(result.vault_path)
            elif result.outcome == OUTCOME_PARTIAL:
                output.partial.append(result.vault_path)
            elif result.outcome == OUTCOME_SKIPPED:
                output.skipped.append(result.vault_path)
            elif result.outcome == OUTCOME_FAILED:
                output.failed.append(result.vault_path)
                output.failure_reasons.append(result.reason)
            # OUTCOME_VANISHED: deregistered between listing and indexing. Counted
            # in documents_seen and otherwise ignored — there is nothing to report
            # about a document that no longer exists.

        return output


ALL_OBSIDIAN_WORKFLOWS = [ObsidianIndexWorkflow]
