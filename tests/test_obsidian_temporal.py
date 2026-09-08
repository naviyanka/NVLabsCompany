"""Tests for the durable Obsidian indexing workflow (ADR 0002 §23, Phase 1C).

Three layers, each proving something the others cannot:

- **Determinism and registration** — static checks that the workflow body cannot
  break Temporal's replay contract, and that the worker knows about it.
- **Real workflow execution** — a ``WorkflowEnvironment`` runs the actual workflow
  against stubbed activities, so orchestration is exercised by Temporal itself
  rather than by calling the body directly.
- **Route contract** — that ``POST /index`` hands work to the workflow instead of
  doing it too, which is the single-writer invariant from ADR 0001.

Activity bodies are covered by the existing indexer tests; what is new here is the
orchestration around them.
"""

from __future__ import annotations

import ast
import inspect
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from nexus.temporal.obsidian_activities import (
    OUTCOME_FAILED,
    OUTCOME_INDEXED,
    OUTCOME_PARTIAL,
    OUTCOME_SKIPPED,
    OUTCOME_VANISHED,
    IndexDocumentInput,
    IndexDocumentOutput,
    PendingDocumentsInput,
    PendingDocumentsOutput,
    index_obsidian_document_activity,
    list_pending_obsidian_documents_activity,
)
from nexus.temporal.obsidian_workflow import (
    ObsidianIndexInput,
    ObsidianIndexOutput,
    ObsidianIndexWorkflow,
)

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ---------------------------------------------------------------------------
# Determinism and registration
# ---------------------------------------------------------------------------


class TestWorkflowDeterminism:
    """Temporal replays workflow code, so the body must be pure orchestration.

    A clock read, a random value, a filesystem touch or a database session inside
    the body makes a replay diverge from the original run — silently, and only
    under a worker restart, which is exactly when durability is supposed to help.
    """

    FORBIDDEN_CALLS = {
        "now", "utcnow", "today", "time", "monotonic", "perf_counter",
        "uuid1", "uuid4", "random", "randint", "choice", "shuffle",
        "open", "sleep",
    }
    FORBIDDEN_NAMES = {
        "AsyncSession", "async_session_factory", "async_sessionmaker",
        "VaultIndexer", "VaultScanner", "ObsidianReader", "RAGPipeline",
        "httpx", "requests", "Path",
    }

    def _workflow_body(self) -> ast.AST:
        source = inspect.getsource(ObsidianIndexWorkflow)
        return ast.parse(inspect.cleandoc(source))

    def test_body_makes_no_nondeterministic_calls(self) -> None:
        """No clock, no randomness, no file handles inside the workflow."""
        offenders = []
        for node in ast.walk(self._workflow_body()):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name in self.FORBIDDEN_CALLS:
                offenders.append(f"{name}() at line {node.lineno}")
        assert offenders == [], f"non-deterministic calls in workflow body: {offenders}"

    def test_body_touches_no_io_or_database_symbols(self) -> None:
        """The body names no session, no reader, no indexer, no HTTP client."""
        offenders = []
        for node in ast.walk(self._workflow_body()):
            if isinstance(node, ast.Name) and node.id in self.FORBIDDEN_NAMES:
                offenders.append(f"{node.id} at line {node.lineno}")
            if isinstance(node, ast.Attribute) and node.attr in self.FORBIDDEN_NAMES:
                offenders.append(f".{node.attr} at line {node.lineno}")
        assert offenders == [], f"I/O symbols in workflow body: {offenders}"

    def test_workflow_module_imports_activities_through_the_sandbox(self) -> None:
        """Activity imports must sit inside ``imports_passed_through()``.

        Temporal's sandbox reimports modules a workflow references; passing them
        through is how the SDK is told not to. Without it the worker fails to
        register the workflow at runtime, which no unit test would catch.
        """
        source = Path(
            inspect.getsourcefile(ObsidianIndexWorkflow)  # type: ignore[arg-type]
        ).read_text(encoding="utf-8")
        assert "with imports_passed_through():" in source
        guarded = source.split("with imports_passed_through():", 1)[1]
        # The activity import block follows the guard.
        assert "obsidian_activities" in guarded.split("\n\n", 1)[0]

    def test_billable_activity_runs_once_only(self) -> None:
        """Embedding is billed per call, so a Temporal retry would charge twice.

        ADR 0001 requires ONCE_ONLY for billed activities; the application's own
        bounded ``attempt_count`` retry is what gives a failed document another
        chance, on a later pass.
        """
        source = inspect.getsource(ObsidianIndexWorkflow)
        index_call = source.split("index_obsidian_document_activity", 1)[1]
        assert "ONCE_ONLY" in index_call.split(")")[0] + index_call.split("\n\n")[0]

    def test_registered_with_the_worker(self) -> None:
        """A workflow the worker does not know about would queue forever."""
        from nexus.temporal.activities import ALL_ACTIVITIES
        from nexus.temporal.workflows import ALL_WORKFLOWS

        assert ObsidianIndexWorkflow in ALL_WORKFLOWS
        assert list_pending_obsidian_documents_activity in ALL_ACTIVITIES
        assert index_obsidian_document_activity in ALL_ACTIVITIES


# ---------------------------------------------------------------------------
# Serialization across the workflow/activity boundary
# ---------------------------------------------------------------------------


class TestBoundaryTypes:
    """Everything crossing the boundary travels as JSON, so it must survive it."""

    def test_dtos_round_trip_through_json(self) -> None:
        """Dataclasses in, dataclasses out, with no UUID or tuple in the way."""
        from temporalio.converter import DataConverter

        converter = DataConverter.default.payload_converter
        for value in (
            ObsidianIndexInput(company_id=str(COMPANY_A), limit=5),
            PendingDocumentsInput(company_id=str(COMPANY_A)),
            PendingDocumentsOutput(nexus_ids=[str(uuid.uuid4())]),
            IndexDocumentInput(company_id=str(COMPANY_A), nexus_id=str(uuid.uuid4())),
            IndexDocumentOutput(
                nexus_id=str(uuid.uuid4()),
                outcome=OUTCOME_INDEXED,
                vault_path="Knowledge/A.md",
                chunks_written=3,
            ),
            ObsidianIndexOutput(company_id=str(COMPANY_A), indexed=["Knowledge/A.md"]),
        ):
            payload = converter.to_payload(value)
            restored = converter.from_payload(payload, type(value))
            assert restored == value, f"{type(value).__name__} did not survive JSON"

    def test_ids_cross_as_strings(self) -> None:
        """UUIDs do not round-trip as UUIDs, so the DTOs use strings deliberately.

        Resolved with ``get_type_hints`` rather than read off ``__annotations__``:
        the activities module uses ``from __future__ import annotations``, so raw
        annotations are strings and a plain identity check would compare ``"str"``
        against ``str``.
        """
        from typing import get_type_hints

        assert get_type_hints(ObsidianIndexInput)["company_id"] is str
        assert get_type_hints(IndexDocumentInput)["nexus_id"] is str
        assert get_type_hints(IndexDocumentInput)["company_id"] is str


# ---------------------------------------------------------------------------
# Real workflow execution
# ---------------------------------------------------------------------------


def _stub_activities(pending: list[str], outcomes: dict[str, IndexDocumentOutput]):
    """Activity stubs registered under the real activity names.

    The workflow is exercised for real by Temporal; only the activity bodies are
    replaced, because their behaviour is covered by the indexer tests and running
    them here would need a vault and a database.
    """
    from temporalio import activity

    calls: list[str] = []

    @activity.defn(name="list_pending_obsidian_documents_activity")
    async def fake_list(input: PendingDocumentsInput) -> PendingDocumentsOutput:
        calls.append("list")
        ids = pending if input.limit is None else pending[: input.limit]
        return PendingDocumentsOutput(nexus_ids=ids)

    @activity.defn(name="index_obsidian_document_activity")
    async def fake_index(input: IndexDocumentInput) -> IndexDocumentOutput:
        calls.append(f"index:{input.nexus_id}")
        return outcomes[input.nexus_id]

    return [fake_list, fake_index], calls


async def _run_workflow(pending, outcomes, limit=None) -> tuple[ObsidianIndexOutput, list[str]]:
    """Execute the real workflow in a time-skipping Temporal environment."""
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    activities, calls = _stub_activities(pending, outcomes)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="obsidian-test",
            workflows=[ObsidianIndexWorkflow],
            activities=activities,
        ):
            result = await env.client.execute_workflow(
                ObsidianIndexWorkflow.run,
                ObsidianIndexInput(company_id=str(COMPANY_A), limit=limit),
                id=f"obsidian-index-test-{uuid.uuid4()}",
                task_queue="obsidian-test",
            )
    return result, calls


def _outcome(nexus_id: str, outcome: str, path: str, chunks: int = 0, reason: str = ""):
    return IndexDocumentOutput(
        nexus_id=nexus_id,
        outcome=outcome,
        vault_path=path,
        chunks_written=chunks,
        reason=reason,
    )


@pytest.mark.asyncio
class TestWorkflowExecution:
    """The workflow, run by Temporal, over stubbed activities."""

    async def test_indexes_every_pending_document(self) -> None:
        """One activity per document, and each result lands in the right bucket."""
        ids = [str(uuid.uuid4()) for _ in range(3)]
        outcomes = {
            ids[0]: _outcome(ids[0], OUTCOME_INDEXED, "Knowledge/A.md", chunks=2),
            ids[1]: _outcome(ids[1], OUTCOME_PARTIAL, "Knowledge/B.md", chunks=1),
            ids[2]: _outcome(ids[2], OUTCOME_SKIPPED, "Knowledge/C.md"),
        }

        result, calls = await _run_workflow(ids, outcomes)

        assert result.indexed == ["Knowledge/A.md"]
        assert result.partial == ["Knowledge/B.md"]
        assert result.skipped == ["Knowledge/C.md"]
        assert result.documents_seen == 3
        assert result.chunks_written == 3
        assert calls == ["list"] + [f"index:{i}" for i in ids]

    async def test_empty_vault_does_no_indexing_work(self) -> None:
        """Nothing pending means one listing activity and nothing else."""
        result, calls = await _run_workflow([], {})

        assert result.counts() == {
            "indexed": 0, "partial": 0, "failed": 0, "skipped": 0, "chunks_written": 0,
        }
        assert calls == ["list"]

    async def test_one_failure_does_not_stop_the_run(self) -> None:
        """A failed document is recorded; the rest still get indexed."""
        ids = [str(uuid.uuid4()) for _ in range(3)]
        outcomes = {
            ids[0]: _outcome(ids[0], OUTCOME_INDEXED, "Knowledge/Good.md", chunks=1),
            ids[1]: _outcome(ids[1], OUTCOME_FAILED, "Knowledge/Bad.md", reason="FileNotFoundError"),
            ids[2]: _outcome(ids[2], OUTCOME_INDEXED, "Knowledge/Also.md", chunks=1),
        }

        result, calls = await _run_workflow(ids, outcomes)

        assert result.indexed == ["Knowledge/Good.md", "Knowledge/Also.md"]
        assert result.failed == ["Knowledge/Bad.md"]
        assert result.failure_reasons == ["FileNotFoundError"]
        assert len(calls) == 4, "the run stopped early"

    async def test_vanished_document_is_counted_but_not_reported(self) -> None:
        """A document deregistered mid-run is not an error and not a result."""
        ids = [str(uuid.uuid4())]
        outcomes = {ids[0]: _outcome(ids[0], OUTCOME_VANISHED, "")}

        result, _ = await _run_workflow(ids, outcomes)

        assert result.documents_seen == 1
        assert result.indexed == result.partial == result.skipped == result.failed == []

    async def test_limit_is_passed_to_the_listing_activity(self) -> None:
        """Batching a large first index is the listing activity's job, not the loop's."""
        ids = [str(uuid.uuid4()) for _ in range(5)]
        outcomes = {i: _outcome(i, OUTCOME_INDEXED, f"Knowledge/{n}.md", 1) for n, i in enumerate(ids)}

        result, calls = await _run_workflow(ids, outcomes, limit=2)

        assert result.documents_seen == 2
        assert len([c for c in calls if c.startswith("index:")]) == 2

    async def test_failure_reasons_carry_no_host_paths(self) -> None:
        """Reasons reach operators and API clients, so they stay path-free."""
        ids = [str(uuid.uuid4())]
        outcomes = {
            ids[0]: _outcome(ids[0], OUTCOME_FAILED, "Knowledge/A.md", reason="FileNotFoundError")
        }

        result, _ = await _run_workflow(ids, outcomes)

        for reason in result.failure_reasons:
            assert "C:\\" not in reason
            assert "/Users/" not in reason


# ---------------------------------------------------------------------------
# Route contract: one writer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRouteDelegation:
    """``POST /index`` either submits the workflow or indexes inline — never both."""

    async def test_returns_202_and_does_not_index_inline(self) -> None:
        """With Temporal on, the request submits work and touches nothing itself."""
        from nexus.api.routes import obsidian as routes

        db = AsyncMock()
        with patch(
            "nexus.temporal.client.start_obsidian_index_workflow",
            AsyncMock(return_value="obsidian-index-abc"),
        ):
            with patch.object(
                routes.ObsidianVaultService, "index", AsyncMock()
            ) as inline_index:
                response = await routes.index_obsidian_vault(db, COMPANY_A, None)

        assert response.status_code == 202
        inline_index.assert_not_awaited(), "the route indexed inline as well as submitting"
        db.commit.assert_not_awaited()

    async def test_202_body_omits_counts(self) -> None:
        """Reporting zeros for an unfinished run would be a lie."""
        import json

        from nexus.api.routes import obsidian as routes

        with patch(
            "nexus.temporal.client.start_obsidian_index_workflow",
            AsyncMock(return_value="obsidian-index-abc"),
        ):
            response = await routes.index_obsidian_vault(AsyncMock(), COMPANY_A, None)

        body = json.loads(response.body)
        assert body["mode"] == "durable"
        assert body["workflow_id"] == "obsidian-index-abc"
        assert "counts" not in body

    async def test_falls_back_to_synchronous_when_temporal_is_off(self) -> None:
        """Temporal disabled or unreachable keeps the old behaviour exactly."""
        from nexus.api.routes import obsidian as routes
        from nexus.obsidian.indexer import IndexResult

        result = IndexResult(indexed=["Knowledge/A.md"], chunks_written=2)
        with patch(
            "nexus.temporal.client.start_obsidian_index_workflow",
            AsyncMock(return_value=None),
        ):
            with patch.object(
                routes.ObsidianVaultService, "index", AsyncMock(return_value=result)
            ) as inline_index:
                response = await routes.index_obsidian_vault(AsyncMock(), COMPANY_A, None)

        inline_index.assert_awaited_once()
        assert response.counts.indexed == 1
        assert response.indexed == ["Knowledge/A.md"]

    async def test_duplicate_run_is_a_conflict_not_a_silent_fallback(self) -> None:
        """A run already in flight must not send the caller down the inline path.

        That would put two writers on one company's documents, which is the defect
        the workflow-id conflict policy exists to prevent.
        """
        from fastapi import HTTPException

        from nexus.api.routes import obsidian as routes
        from nexus.temporal.client import ObsidianIndexAlreadyRunningError

        with patch(
            "nexus.temporal.client.start_obsidian_index_workflow",
            AsyncMock(side_effect=ObsidianIndexAlreadyRunningError("busy")),
        ):
            with patch.object(
                routes.ObsidianVaultService, "index", AsyncMock()
            ) as inline_index:
                with pytest.raises(HTTPException) as excinfo:
                    await routes.index_obsidian_vault(AsyncMock(), COMPANY_A, None)

        assert excinfo.value.status_code == 409
        inline_index.assert_not_awaited()

    async def test_scan_is_unaffected(self) -> None:
        """Only indexing moved to Temporal; scan stays synchronous by design."""
        import inspect as _inspect

        from nexus.api.routes import obsidian as routes

        source = _inspect.getsource(routes.scan_obsidian_vault)
        assert "workflow" not in source.lower()


class TestClientStarter:
    """The starter's contract, without needing a Temporal server."""

    def test_workflow_id_is_per_company(self) -> None:
        """One id per company is what makes Temporal reject a concurrent run."""
        source = inspect.getsource(
            __import__("nexus.temporal.client", fromlist=["x"]).start_obsidian_index_workflow
        )
        assert 'f"obsidian-index-{company_id}"' in source
        assert "WorkflowIDConflictPolicy.FAIL" in source

    def test_already_started_error_is_handled_explicitly(self) -> None:
        """WorkflowAlreadyStartedError is not an RPCError, so it needs its own clause.

        Catching only RPCError let a duplicate fall through, return None, and send
        the caller down the synchronous path while a workflow was already running.
        """
        from temporalio.exceptions import WorkflowAlreadyStartedError
        from temporalio.service import RPCError

        assert not issubclass(WorkflowAlreadyStartedError, RPCError)

        source = inspect.getsource(
            __import__("nexus.temporal.client", fromlist=["x"]).start_obsidian_index_workflow
        )
        assert "except WorkflowAlreadyStartedError" in source


# ---------------------------------------------------------------------------
# Exception classification: whose failure is it
# ---------------------------------------------------------------------------


def _security(name: str):
    """One of the vault security exceptions, by class name."""
    import nexus.obsidian.security as sec

    return getattr(sec, name)


class TestExceptionClassification:
    """Which failures belong to one document, and which to the whole run.

    Isolating an environmental failure would spend every remaining document's
    retry budget re-proving the same thing, and leave a vault marked failed for a
    reason that had nothing to do with the notes. Isolating a document's own
    failure is what lets a batch make progress past one bad note.
    """

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError("gone"),
            PermissionError("denied"),
            ConnectionError("provider unreachable"),
            TimeoutError("provider timed out"),
            ValueError("unsupported content"),
            KeyError("missing field"),
            RuntimeError("something odd in this note"),
        ],
    )
    def test_document_scoped_failures_are_isolated(self, exc) -> None:
        """A failure about one note must not take the batch down.

        ``OSError`` is checked before the programming-error family deliberately,
        so an unreadable file stays this document's problem.
        """
        from nexus.temporal.obsidian_activities import _is_workflow_fatal

        assert _is_workflow_fatal(exc) is False

    @pytest.mark.parametrize(
        "name",
        ["VaultBoundaryError", "VaultExtensionError", "VaultFileTooLargeError"],
    )
    def test_path_rejections_are_isolated_not_swallowed(self, name) -> None:
        """A refused path is recorded and logged, not allowed to stop the run.

        The boundary did its job; one bad filename must not stop a vault from
        indexing. Nothing is swallowed — the reason is persisted on the row and
        logged at exception level.
        """
        from nexus.temporal.obsidian_activities import _is_workflow_fatal

        assert _is_workflow_fatal(_security(name)("refused")) is False

    @pytest.mark.parametrize(
        "exc",
        [
            MemoryError("out of memory"),
            RecursionError("too deep"),
            NameError("typo in a symbol"),
            ImportError("missing module"),
            AttributeError("wrong shape"),
            TypeError("wrong argument"),
        ],
    )
    def test_environmental_and_programming_failures_are_fatal(self, exc) -> None:
        """These would recur for every document, so the run stops instead."""
        from nexus.temporal.obsidian_activities import _is_workflow_fatal

        assert _is_workflow_fatal(exc) is True

    @pytest.mark.parametrize(
        "name", ["VaultNotConfiguredError", "VaultConfigurationError"]
    )
    def test_configuration_failures_are_fatal(self, name) -> None:
        """No document can be read when the vault root is unusable."""
        from nexus.temporal.obsidian_activities import _is_workflow_fatal

        assert _is_workflow_fatal(_security(name)("bad root")) is True

    def test_database_connection_failure_is_fatal(self) -> None:
        """If the connection is unusable, the next document cannot be written."""
        from sqlalchemy.exc import OperationalError

        from nexus.temporal.obsidian_activities import _is_workflow_fatal

        assert _is_workflow_fatal(OperationalError("stmt", {}, Exception("gone"))) is True


# ---------------------------------------------------------------------------
# Batch isolation: A succeeds, B fails, C succeeds
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestBatchIsolation:
    """The run must not end at the document that failed."""

    async def test_unexpected_document_failure_does_not_abandon_the_batch(self) -> None:
        """A indexed, B failed, C indexed, and the workflow completed."""
        ids = [str(uuid.uuid4()) for _ in range(3)]
        outcomes = {
            ids[0]: _outcome(ids[0], OUTCOME_INDEXED, "Knowledge/A.md", chunks=1),
            # What the activity returns once it isolates an unexpected error.
            ids[1]: _outcome(ids[1], OUTCOME_FAILED, "", reason="RuntimeError"),
            ids[2]: _outcome(ids[2], OUTCOME_INDEXED, "Knowledge/C.md", chunks=1),
        }

        result, calls = await _run_workflow(ids, outcomes)

        assert result.indexed == ["Knowledge/A.md", "Knowledge/C.md"]
        assert result.failure_reasons == ["RuntimeError"]
        assert len([c for c in calls if c.startswith("index:")]) == 3, (
            "the workflow stopped before reaching document C"
        )

    async def test_workflow_fails_on_a_fatal_condition(self) -> None:
        """An environmental failure surfaces as a failed workflow, explicitly."""
        from temporalio import activity
        from temporalio.client import WorkflowFailureError
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        ids = [str(uuid.uuid4())]

        @activity.defn(name="list_pending_obsidian_documents_activity")
        async def fake_list(input: PendingDocumentsInput) -> PendingDocumentsOutput:
            return PendingDocumentsOutput(nexus_ids=ids)

        @activity.defn(name="index_obsidian_document_activity")
        async def fatal_index(input: IndexDocumentInput) -> IndexDocumentOutput:
            raise MemoryError("the process is unwell")

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="obsidian-fatal",
                workflows=[ObsidianIndexWorkflow],
                activities=[fake_list, fatal_index],
            ):
                with pytest.raises(WorkflowFailureError):
                    await env.client.execute_workflow(
                        ObsidianIndexWorkflow.run,
                        ObsidianIndexInput(company_id=str(COMPANY_A)),
                        id=f"obsidian-fatal-{uuid.uuid4()}",
                        task_queue="obsidian-fatal",
                    )


# ---------------------------------------------------------------------------
# What an isolated failure does to the database
# ---------------------------------------------------------------------------


@pytest.fixture
async def indexed_vault(tmp_path):
    """A vault with one note already indexed, and its session factory.

    Built by running the real scan-then-index path, so the chunks under test are
    the ones production would have written.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from nexus.knowledge.embeddings import LocalEmbeddingProvider
    from nexus.knowledge.parsers import MarkdownParser
    from nexus.knowledge.rag import RAGPipeline
    from nexus.models.knowledge import KnowledgeChunk
    from nexus.models.obsidian import ObsidianDocument
    from nexus.obsidian import VaultIndexer, VaultScanner

    root = tmp_path / "vaults"
    (root / str(COMPANY_A)).mkdir(parents=True)
    (root / str(COMPANY_A) / "A.md").write_text(
        "# Heading\n\nOrdinary prose about deployment runbooks.\n", encoding="utf-8"
    )

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'x.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[ObsidianDocument.__table__, KnowledgeChunk.__table__],
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(root)
        mock_settings.obsidian_max_note_bytes = 1_048_576

        async with factory() as db:
            await VaultScanner(db, COMPANY_A).scan()
            await db.commit()
        async with factory() as db:
            pipeline = RAGPipeline(
                db=db,
                embedding_provider=LocalEmbeddingProvider(),
                parser=MarkdownParser(),
            )
            await VaultIndexer(db, COMPANY_A, pipeline=pipeline).index_stale()
            await db.commit()

        yield root, factory
    await engine.dispose()


async def _chunk_contents(factory) -> list[str]:
    from sqlalchemy import select

    from nexus.models.knowledge import KnowledgeChunk

    async with factory() as db:
        rows = (await db.execute(select(KnowledgeChunk))).scalars().all()
    return sorted(c.content for c in rows)


async def _the_document(factory):
    from sqlalchemy import select

    from nexus.models.obsidian import ObsidianDocument

    async with factory() as db:
        return (await db.execute(select(ObsidianDocument))).scalars().one()


@pytest.mark.asyncio
class TestIsolatedFailureRecording:
    """An isolated failure is persisted, bounded, and destroys nothing."""

    async def test_failure_is_recorded_and_spends_one_attempt(
        self, indexed_vault
    ) -> None:
        """The row is marked failed, and the retry budget moves by exactly one."""
        from nexus.models.obsidian import INDEX_STATUS_FAILED, MAX_INDEX_ATTEMPTS
        from nexus.obsidian import VaultIndexer

        _, factory = indexed_vault
        nexus_id = (await _the_document(factory)).nexus_id

        async with factory() as db:
            marked = await VaultIndexer(db, COMPANY_A).record_failure(
                nexus_id, ConnectionError("provider down")
            )
            await db.commit()

        assert marked is True
        doc = await _the_document(factory)
        assert doc.index_status == INDEX_STATUS_FAILED
        assert doc.attempt_count == 1, "one isolated failure, one attempt"
        assert doc.attempt_count < MAX_INDEX_ATTEMPTS, "still retryable on a later pass"
        assert doc.last_error == "ConnectionError"

    async def test_recorded_reason_carries_no_host_path(self, indexed_vault) -> None:
        """The persisted reason reaches API clients, so it stays path-free."""
        from nexus.obsidian import VaultIndexer

        root, factory = indexed_vault
        nexus_id = (await _the_document(factory)).nexus_id

        async with factory() as db:
            await VaultIndexer(db, COMPANY_A).record_failure(
                nexus_id, FileNotFoundError(f"[Errno 2] No such file: '{root}/A.md'")
            )
            await db.commit()

        doc = await _the_document(factory)
        assert doc.last_error == "FileNotFoundError"
        assert str(root) not in doc.last_error
        assert "C:\\" not in doc.last_error

    async def test_failure_neither_destroys_nor_duplicates_existing_chunks(
        self, indexed_vault
    ) -> None:
        """The invariant: a failed attempt never damages a working index."""
        from nexus.obsidian import VaultIndexer

        _, factory = indexed_vault
        before = await _chunk_contents(factory)
        assert before, "nothing was indexed, so the test proves nothing"

        nexus_id = (await _the_document(factory)).nexus_id
        async with factory() as db:
            await VaultIndexer(db, COMPANY_A).record_failure(
                nexus_id, RuntimeError("unexpected")
            )
            await db.commit()

        assert await _chunk_contents(factory) == before, (
            "recording a failure changed the stored chunks"
        )

    async def test_recording_against_a_deregistered_document_is_harmless(
        self, indexed_vault
    ) -> None:
        """A document removed mid-run has nothing to mark, and that is not an error."""
        from nexus.obsidian import VaultIndexer

        _, factory = indexed_vault
        async with factory() as db:
            marked = await VaultIndexer(db, COMPANY_A).record_failure(
                uuid.uuid4(), RuntimeError("boom")
            )
        assert marked is False


# ---------------------------------------------------------------------------
# Progress query: closing the loop on the 202
# ---------------------------------------------------------------------------


class TestProgressQueryHandler:
    """The workflow answers "how far along" from its own state."""

    def test_fresh_workflow_reports_nothing_done(self) -> None:
        """Before the listing activity returns, the total is 0, not a guess."""
        progress = ObsidianIndexWorkflow().progress()

        assert progress.documents_total == 0
        assert progress.documents_seen == 0
        assert progress.remaining == 0
        assert progress.indexed == progress.partial == progress.failed == 0

    def test_handler_only_reads_workflow_state(self) -> None:
        """A query may be replayed, so it must not mutate or run an activity.

        Checked statically: an assignment to ``self`` or an ``execute_activity``
        call inside the handler is the defect, and it would only show up under a
        replay, which no ordinary test exercises.
        """
        tree = ast.parse(inspect.cleandoc(inspect.getsource(ObsidianIndexWorkflow)))
        handler = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "progress"
        )
        for node in ast.walk(handler):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
                raise AssertionError(f"the query handler assigns state at line {node.lineno}")
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                assert name != "execute_activity", "the query handler runs an activity"

    def test_progress_dto_survives_the_json_boundary(self) -> None:
        """A query result crosses the same boundary as everything else."""
        from temporalio.converter import DataConverter

        from nexus.temporal.obsidian_workflow import ObsidianIndexProgress

        value = ObsidianIndexProgress(
            company_id=str(COMPANY_A), documents_total=3, documents_seen=1, remaining=2
        )
        converter = DataConverter.default.payload_converter
        restored = converter.from_payload(converter.to_payload(value), ObsidianIndexProgress)
        assert restored == value


@pytest.mark.asyncio
class TestProgressQueryUnderTemporal:
    """Queried through Temporal, against a real running workflow."""

    async def test_progress_is_answerable_mid_run(self) -> None:
        """The point of the query: counts while the run is still going.

        The second document's activity blocks until the test has queried, so the
        assertion is made against a genuinely in-flight run rather than a finished
        one.
        """
        import asyncio

        from temporalio import activity
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        ids = [str(uuid.uuid4()) for _ in range(2)]
        released = asyncio.Event()

        @activity.defn(name="list_pending_obsidian_documents_activity")
        async def fake_list(input: PendingDocumentsInput) -> PendingDocumentsOutput:
            return PendingDocumentsOutput(nexus_ids=ids)

        @activity.defn(name="index_obsidian_document_activity")
        async def slow_index(input: IndexDocumentInput) -> IndexDocumentOutput:
            if input.nexus_id == ids[1]:
                await released.wait()
            return _outcome(input.nexus_id, OUTCOME_INDEXED, "Knowledge/X.md", chunks=1)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="obsidian-progress",
                workflows=[ObsidianIndexWorkflow],
                activities=[fake_list, slow_index],
            ):
                handle = await env.client.start_workflow(
                    ObsidianIndexWorkflow.run,
                    ObsidianIndexInput(company_id=str(COMPANY_A)),
                    id=f"obsidian-progress-{uuid.uuid4()}",
                    task_queue="obsidian-progress",
                )
                try:
                    async def first_document_done():
                        while True:
                            progress = await handle.query(ObsidianIndexWorkflow.progress)
                            if progress.documents_seen == 1:
                                return progress
                            await asyncio.sleep(0.05)

                    mid = await asyncio.wait_for(first_document_done(), timeout=30)
                finally:
                    released.set()

                assert mid.documents_total == 2
                assert mid.documents_seen == 1
                assert mid.remaining == 1, "remaining did not track the work left"
                assert mid.indexed == 1
                assert mid.chunks_written == 1
                assert mid.company_id == str(COMPANY_A)

                final = await handle.result()
                assert final.documents_seen == 2

    async def test_progress_matches_the_final_result(self) -> None:
        """Whatever the query reports must be the same accounting as the result."""
        from temporalio.testing import WorkflowEnvironment
        from temporalio.worker import Worker

        ids = [str(uuid.uuid4()) for _ in range(3)]
        outcomes = {
            ids[0]: _outcome(ids[0], OUTCOME_INDEXED, "Knowledge/A.md", chunks=2),
            ids[1]: _outcome(ids[1], OUTCOME_FAILED, "Knowledge/B.md", reason="RuntimeError"),
            ids[2]: _outcome(ids[2], OUTCOME_PARTIAL, "Knowledge/C.md", chunks=1),
        }
        activities, _ = _stub_activities(ids, outcomes)

        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue="obsidian-progress-final",
                workflows=[ObsidianIndexWorkflow],
                activities=activities,
            ):
                handle = await env.client.start_workflow(
                    ObsidianIndexWorkflow.run,
                    ObsidianIndexInput(company_id=str(COMPANY_A)),
                    id=f"obsidian-progress-final-{uuid.uuid4()}",
                    task_queue="obsidian-progress-final",
                )
                result = await handle.result()
                # A closed execution still answers a query, by replay.
                progress = await handle.query(ObsidianIndexWorkflow.progress)

        assert progress.documents_seen == result.documents_seen == 3
        assert progress.remaining == 0
        assert progress.indexed == 1
        assert progress.partial == 1
        assert progress.failed == 1
        assert progress.chunks_written == result.chunks_written == 3


@pytest.mark.asyncio
class TestProgressLookupIsolation:
    """A caller can only ever address their own company's run."""

    async def test_another_companys_workflow_is_not_even_queried(self) -> None:
        """The id is rebuilt from the caller's company, not taken on trust.

        Structural rather than checked after the fact: if this only filtered a
        queried result, the other company's run would still be reachable and its
        existence observable. The Temporal client must not be touched at all.
        """
        from nexus.temporal.client import (
            ObsidianIndexNotFoundError,
            query_obsidian_index_progress,
        )

        other = uuid.uuid4()
        with patch(
            "nexus.temporal.client._get_client",
            AsyncMock(side_effect=AssertionError("Temporal was contacted")),
        ):
            with pytest.raises(ObsidianIndexNotFoundError):
                await query_obsidian_index_progress(
                    str(COMPANY_A), f"obsidian-index-{other}"
                )

    async def test_the_id_is_the_one_the_starter_issues(self) -> None:
        """A caller polls the id they were given, so the two must agree."""
        from nexus.temporal.client import obsidian_index_workflow_id

        source = inspect.getsource(
            __import__("nexus.temporal.client", fromlist=["x"]).start_obsidian_index_workflow
        )
        assert f'id=f"obsidian-index-{{company_id}}"' in source
        assert obsidian_index_workflow_id(str(COMPANY_A)) == f"obsidian-index-{COMPANY_A}"

    async def test_temporal_disabled_is_not_a_missing_run(self) -> None:
        """With Temporal off, indexing is synchronous and no id was ever issued."""
        from nexus.temporal.client import (
            ObsidianIndexUnavailableError,
            obsidian_index_workflow_id,
            query_obsidian_index_progress,
        )

        with patch("nexus.temporal.client.is_temporal_enabled", return_value=False):
            with pytest.raises(ObsidianIndexUnavailableError):
                await query_obsidian_index_progress(
                    str(COMPANY_A), obsidian_index_workflow_id(str(COMPANY_A))
                )

    async def test_a_closed_run_reports_state_without_counts(self) -> None:
        """A finished execution has no handler left, so counts are omitted.

        Reporting zeros there would claim the run indexed nothing.
        """
        from temporalio.client import WorkflowExecutionStatus

        from nexus.temporal.client import (
            obsidian_index_workflow_id,
            query_obsidian_index_progress,
        )

        handle = AsyncMock()
        handle.describe.return_value = type(
            "Desc", (), {"status": WorkflowExecutionStatus.COMPLETED}
        )()
        client = AsyncMock()
        client.get_workflow_handle = lambda *a, **k: handle

        with patch("nexus.temporal.client.is_temporal_enabled", return_value=True):
            with patch("nexus.temporal.client._get_client", AsyncMock(return_value=client)):
                progress = await query_obsidian_index_progress(
                    str(COMPANY_A), obsidian_index_workflow_id(str(COMPANY_A))
                )

        assert progress == {
            "workflow_id": f"obsidian-index-{COMPANY_A}",
            "state": "completed",
        }
        handle.query.assert_not_awaited()

    @pytest.mark.parametrize(
        ("status_name", "expected"),
        [
            ("RUNNING", "running"),
            ("COMPLETED", "completed"),
            ("FAILED", "failed"),
            ("CANCELED", "cancelled"),
            ("TERMINATED", "terminated"),
            ("TIMED_OUT", "timed_out"),
        ],
    )
    async def test_execution_states_are_reported_honestly(
        self, status_name, expected
    ) -> None:
        """Including the states this code was not written around."""
        from temporalio.client import WorkflowExecutionStatus

        from nexus.temporal.client import _execution_state

        assert _execution_state(getattr(WorkflowExecutionStatus, status_name)) == expected


@pytest.mark.asyncio
class TestProgressRoute:
    """The HTTP surface over the query."""

    async def test_returns_the_counts_for_this_companys_run(self) -> None:
        from nexus.api.routes import obsidian as routes

        payload = {
            "workflow_id": f"obsidian-index-{COMPANY_A}",
            "state": "running",
            "documents_total": 4,
            "documents_seen": 1,
            "remaining": 3,
            "chunks_written": 2,
            "indexed": 1,
            "partial": 0,
            "skipped": 0,
            "failed": 0,
        }
        with patch(
            "nexus.temporal.client.query_obsidian_index_progress",
            AsyncMock(return_value=payload),
        ) as query:
            response = await routes.get_obsidian_index_progress(
                COMPANY_A, f"obsidian-index-{COMPANY_A}"
            )

        query.assert_awaited_once_with(str(COMPANY_A), f"obsidian-index-{COMPANY_A}")
        assert response.state == "running"
        assert response.remaining == 3
        assert response.documents_seen == 1

    async def test_a_closed_run_omits_counts_rather_than_zeroing_them(self) -> None:
        from nexus.api.routes import obsidian as routes

        with patch(
            "nexus.temporal.client.query_obsidian_index_progress",
            AsyncMock(return_value={"workflow_id": "obsidian-index-x", "state": "completed"}),
        ):
            response = await routes.get_obsidian_index_progress(COMPANY_A, "obsidian-index-x")

        assert response.state == "completed"
        assert response.documents_seen is None
        assert response.indexed is None

    @pytest.mark.parametrize(
        "error_name", ["ObsidianIndexNotFoundError", "ObsidianIndexUnavailableError"]
    )
    async def test_unknown_and_unavailable_both_answer_404(self, error_name) -> None:
        """One answer for both, so neither leaks whether the run exists."""
        from fastapi import HTTPException

        import nexus.temporal.client as client_module
        from nexus.api.routes import obsidian as routes

        error = getattr(client_module, error_name)("nope")
        with patch(
            "nexus.temporal.client.query_obsidian_index_progress",
            AsyncMock(side_effect=error),
        ):
            with pytest.raises(HTTPException) as excinfo:
                await routes.get_obsidian_index_progress(COMPANY_A, "obsidian-index-x")

        assert excinfo.value.status_code == 404
        assert "company" in excinfo.value.detail

    async def test_the_route_reads_and_writes_nothing(self) -> None:
        """A progress poll takes no session: it is a Temporal read only."""
        params = inspect.signature(
            __import__("nexus.api.routes.obsidian", fromlist=["x"]).get_obsidian_index_progress
        ).parameters
        assert set(params) == {"company_id", "workflow_id"}
