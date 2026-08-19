"""Tests for ToolInvocation model, ToolAuditStore, argument scrubbing, and executor integration."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.models.tool_invocation import ToolInvocation
from nexus.tools.audit import AuditStats, ToolAuditStore
from nexus.tools.executor import ToolExecutor, ToolResult, _scrub_arguments


class TestToolInvocationModel:
    """Tests for ToolInvocation SQLModel instantiation."""

    def test_create_with_required_fields(self) -> None:
        """ToolInvocation can be created with required fields."""
        company_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        tool_id = uuid.uuid4()

        inv = ToolInvocation(
            company_id=company_id,
            agent_id=agent_id,
            tool_id=tool_id,
            tool_name="read_file",
            status="success",
            duration_ms=42,
        )

        assert inv.company_id == company_id
        assert inv.agent_id == agent_id
        assert inv.tool_id == tool_id
        assert inv.tool_name == "read_file"
        assert inv.status == "success"
        assert inv.duration_ms == 42
        assert inv.cost_cents == 0
        assert inv.approval_state == "not_required"
        assert inv.error is None
        assert inv.result_summary is None
        assert inv.connection_id is None
        assert inv.completed_at is None

    def test_create_with_all_fields(self) -> None:
        """ToolInvocation can be created with all fields specified."""
        company_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        tool_id = uuid.uuid4()
        conn_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        inv = ToolInvocation(
            company_id=company_id,
            agent_id=agent_id,
            tool_id=tool_id,
            connection_id=conn_id,
            tool_name="deploy_service",
            arguments_scrubbed={"service": "api", "api_key": "***"},
            result_summary="Deployed successfully",
            status="success",
            duration_ms=1500,
            cost_cents=25,
            approval_state="approved",
            error=None,
            created_at=now,
            completed_at=now,
        )

        assert inv.connection_id == conn_id
        assert inv.arguments_scrubbed == {"service": "api", "api_key": "***"}
        assert inv.result_summary == "Deployed successfully"
        assert inv.cost_cents == 25
        assert inv.approval_state == "approved"
        assert inv.created_at == now
        assert inv.completed_at == now

    def test_importable_from_nexus_models(self) -> None:
        """ToolInvocation is importable from the nexus.models package."""
        from nexus.models import ToolInvocation as TI

        assert TI is ToolInvocation


class TestArgumentScrubbing:
    """Tests for sensitive argument scrubbing logic."""

    def test_scrubs_password_key(self) -> None:
        """Keys containing 'password' are scrubbed."""
        args = {"username": "admin", "password": "supersecret"}
        result = _scrub_arguments(args)
        assert result["username"] == "admin"
        assert result["password"] == "***"

    def test_scrubs_secret_key(self) -> None:
        """Keys containing 'secret' are scrubbed."""
        args = {"client_secret": "abc123", "name": "test"}
        result = _scrub_arguments(args)
        assert result["client_secret"] == "***"
        assert result["name"] == "test"

    def test_scrubs_token_key(self) -> None:
        """Keys containing 'token' are scrubbed."""
        args = {"access_token": "tok_xyz", "endpoint": "https://api.example.com"}
        result = _scrub_arguments(args)
        assert result["access_token"] == "***"
        assert result["endpoint"] == "https://api.example.com"

    def test_scrubs_key_key(self) -> None:
        """Keys containing 'key' are scrubbed."""
        args = {"api_key": "key123", "action": "read"}
        result = _scrub_arguments(args)
        assert result["api_key"] == "***"
        assert result["action"] == "read"

    def test_scrubbing_case_insensitive(self) -> None:
        """Scrubbing matches regardless of case."""
        args = {"API_KEY": "val", "Password": "val", "SECRET_TOKEN": "val"}
        result = _scrub_arguments(args)
        assert result["API_KEY"] == "***"
        assert result["Password"] == "***"
        assert result["SECRET_TOKEN"] == "***"

    def test_no_sensitive_keys_passes_through(self) -> None:
        """Arguments without sensitive keys are passed through unchanged."""
        args = {"filename": "test.txt", "mode": "read", "count": 5}
        result = _scrub_arguments(args)
        assert result == args

    def test_empty_arguments(self) -> None:
        """Empty arguments dictionary returns empty."""
        assert _scrub_arguments({}) == {}


class TestToolAuditStore:
    """Tests for ToolAuditStore record, query, and stats methods."""

    def _make_invocation(
        self,
        agent_id: uuid.UUID | None = None,
        tool_id: uuid.UUID | None = None,
        status: str = "success",
        duration_ms: int = 100,
        cost_cents: int = 0,
        created_at: datetime | None = None,
    ) -> ToolInvocation:
        """Helper to create a ToolInvocation with sensible defaults."""
        return ToolInvocation(
            company_id=uuid.uuid4(),
            agent_id=agent_id or uuid.uuid4(),
            tool_id=tool_id or uuid.uuid4(),
            tool_name="test_tool",
            status=status,
            duration_ms=duration_ms,
            cost_cents=cost_cents,
            created_at=created_at or datetime.now(timezone.utc),
        )

    def test_record_stores_invocation(self) -> None:
        """record() adds invocation to internal storage."""
        store = ToolAuditStore()
        inv = self._make_invocation()
        store.record(inv)
        assert len(store.query()) == 1

    def test_query_returns_all_by_default(self) -> None:
        """query() with no filters returns all records."""
        store = ToolAuditStore()
        for _ in range(5):
            store.record(self._make_invocation())
        assert len(store.query()) == 5

    def test_query_filter_by_agent_id(self) -> None:
        """query() filters by agent_id."""
        store = ToolAuditStore()
        target_agent = uuid.uuid4()
        store.record(self._make_invocation(agent_id=target_agent))
        store.record(self._make_invocation())
        store.record(self._make_invocation(agent_id=target_agent))

        results = store.query(agent_id=target_agent)
        assert len(results) == 2
        assert all(r.agent_id == target_agent for r in results)

    def test_query_filter_by_tool_id(self) -> None:
        """query() filters by tool_id."""
        store = ToolAuditStore()
        target_tool = uuid.uuid4()
        store.record(self._make_invocation(tool_id=target_tool))
        store.record(self._make_invocation())

        results = store.query(tool_id=target_tool)
        assert len(results) == 1
        assert results[0].tool_id == target_tool

    def test_query_filter_by_status(self) -> None:
        """query() filters by status."""
        store = ToolAuditStore()
        store.record(self._make_invocation(status="success"))
        store.record(self._make_invocation(status="error"))
        store.record(self._make_invocation(status="timeout"))

        results = store.query(status="error")
        assert len(results) == 1
        assert results[0].status == "error"

    def test_query_filter_by_since(self) -> None:
        """query() filters records created at or after 'since'."""
        store = ToolAuditStore()
        old_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new_time = datetime(2024, 6, 1, tzinfo=timezone.utc)

        store.record(self._make_invocation(created_at=old_time))
        store.record(self._make_invocation(created_at=new_time))

        cutoff = datetime(2024, 3, 1, tzinfo=timezone.utc)
        results = store.query(since=cutoff)
        assert len(results) == 1
        assert results[0].created_at == new_time

    def test_query_respects_limit(self) -> None:
        """query() respects the limit parameter."""
        store = ToolAuditStore()
        for _ in range(10):
            store.record(self._make_invocation())

        results = store.query(limit=3)
        assert len(results) == 3

    def test_query_returns_most_recent_first(self) -> None:
        """query() returns results most recent first."""
        store = ToolAuditStore()
        t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2024, 6, 1, tzinfo=timezone.utc)
        t3 = datetime(2024, 12, 1, tzinfo=timezone.utc)

        store.record(self._make_invocation(created_at=t1))
        store.record(self._make_invocation(created_at=t2))
        store.record(self._make_invocation(created_at=t3))

        results = store.query()
        assert results[0].created_at == t3
        assert results[1].created_at == t2
        assert results[2].created_at == t1

    def test_get_stats_basic(self) -> None:
        """get_stats() returns correct aggregated statistics."""
        store = ToolAuditStore()
        store.record(self._make_invocation(status="success", duration_ms=100, cost_cents=10))
        store.record(self._make_invocation(status="success", duration_ms=200, cost_cents=20))
        store.record(self._make_invocation(status="error", duration_ms=50, cost_cents=0))

        stats = store.get_stats()
        assert stats.total_invocations == 3
        assert stats.success_count == 2
        assert stats.error_count == 1
        assert stats.total_cost_cents == 30
        assert stats.avg_duration_ms == pytest.approx(350 / 3)

    def test_get_stats_filter_by_agent(self) -> None:
        """get_stats() filters by agent_id."""
        store = ToolAuditStore()
        agent1 = uuid.uuid4()
        agent2 = uuid.uuid4()
        store.record(self._make_invocation(agent_id=agent1, status="success", cost_cents=5))
        store.record(self._make_invocation(agent_id=agent2, status="error", cost_cents=0))

        stats = store.get_stats(agent_id=agent1)
        assert stats.total_invocations == 1
        assert stats.success_count == 1
        assert stats.total_cost_cents == 5

    def test_get_stats_filter_by_since(self) -> None:
        """get_stats() filters by since timestamp."""
        store = ToolAuditStore()
        old = datetime(2024, 1, 1, tzinfo=timezone.utc)
        new = datetime(2024, 6, 1, tzinfo=timezone.utc)
        store.record(self._make_invocation(created_at=old, cost_cents=10))
        store.record(self._make_invocation(created_at=new, cost_cents=20))

        stats = store.get_stats(since=datetime(2024, 3, 1, tzinfo=timezone.utc))
        assert stats.total_invocations == 1
        assert stats.total_cost_cents == 20

    def test_get_stats_empty_store(self) -> None:
        """get_stats() on empty store returns zeroes."""
        store = ToolAuditStore()
        stats = store.get_stats()
        assert stats.total_invocations == 0
        assert stats.success_count == 0
        assert stats.error_count == 0
        assert stats.total_cost_cents == 0
        assert stats.avg_duration_ms == 0.0


class TestExecutorAuditIntegration:
    """Integration tests for ToolExecutor with ToolAuditStore recording."""

    @pytest.fixture
    def audit_store(self) -> ToolAuditStore:
        """Provide a fresh ToolAuditStore instance."""
        return ToolAuditStore()

    @pytest.fixture
    def executor(self, audit_store: ToolAuditStore) -> ToolExecutor:
        """Provide a ToolExecutor with audit_store configured."""
        return ToolExecutor(timeout_seconds=1.0, audit_store=audit_store)

    @pytest.fixture
    def ids(self) -> dict[str, uuid.UUID]:
        """Provide standard test UUIDs."""
        return {
            "agent_id": uuid.uuid4(),
            "tool_id": uuid.uuid4(),
            "company_id": uuid.uuid4(),
        }

    def test_successful_execution_records_invocation(
        self, executor: ToolExecutor, audit_store: ToolAuditStore, ids: dict
    ) -> None:
        """Successful tool execution creates an audit invocation record."""

        async def run():
            async def fn(args):
                return {"result": "ok"}

            await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={"filename": "test.txt"},
                execute_fn=fn,
                company_id=ids["company_id"],
            )

        asyncio.run(run())

        records = audit_store.query()
        assert len(records) == 1
        assert records[0].status == "success"
        assert records[0].agent_id == ids["agent_id"]
        assert records[0].tool_id == ids["tool_id"]
        assert records[0].arguments_scrubbed == {"filename": "test.txt"}

    def test_error_execution_records_invocation(
        self, executor: ToolExecutor, audit_store: ToolAuditStore, ids: dict
    ) -> None:
        """Failed tool execution records error status in audit store."""

        async def run():
            async def fn(args):
                raise ValueError("Something went wrong")

            await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={"action": "delete"},
                execute_fn=fn,
                company_id=ids["company_id"],
            )

        asyncio.run(run())

        records = audit_store.query()
        assert len(records) == 1
        assert records[0].status == "error"
        assert records[0].error == "Something went wrong"

    def test_timeout_execution_records_invocation(
        self, executor: ToolExecutor, audit_store: ToolAuditStore, ids: dict
    ) -> None:
        """Timed-out tool execution records timeout status."""

        async def run():
            async def fn(args):
                await asyncio.sleep(10)

            await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={"query": "slow"},
                execute_fn=fn,
                company_id=ids["company_id"],
            )

        asyncio.run(run())

        records = audit_store.query()
        assert len(records) == 1
        assert records[0].status == "timeout"
        assert records[0].completed_at is None

    def test_denied_execution_records_invocation(
        self, executor: ToolExecutor, audit_store: ToolAuditStore, ids: dict
    ) -> None:
        """Permission-denied execution records denied status."""

        async def deny(agent_id, tool_id):
            return False

        executor.set_permission_checker(deny)

        async def run():
            async def fn(args):
                return "should not reach"

            await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={"data": "test"},
                execute_fn=fn,
                company_id=ids["company_id"],
            )

        asyncio.run(run())

        records = audit_store.query()
        assert len(records) == 1
        assert records[0].status == "denied"

    def test_sensitive_arguments_scrubbed_in_audit(
        self, executor: ToolExecutor, audit_store: ToolAuditStore, ids: dict
    ) -> None:
        """Sensitive argument keys are scrubbed in audit records."""

        async def run():
            async def fn(args):
                return "done"

            await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={
                    "api_key": "sk-12345",
                    "password": "hunter2",
                    "filename": "report.pdf",
                },
                execute_fn=fn,
                company_id=ids["company_id"],
            )

        asyncio.run(run())

        records = audit_store.query()
        assert len(records) == 1
        scrubbed = records[0].arguments_scrubbed
        assert scrubbed["api_key"] == "***"
        assert scrubbed["password"] == "***"
        assert scrubbed["filename"] == "report.pdf"

    def test_no_audit_store_does_not_fail(self, ids: dict) -> None:
        """Executor without audit_store still works normally."""
        executor = ToolExecutor(timeout_seconds=1.0)

        async def run():
            async def fn(args):
                return "ok"

            result = await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={"x": 1},
                execute_fn=fn,
                company_id=ids["company_id"],
            )
            return result

        result = asyncio.run(run())
        assert result.success is True

    def test_no_company_id_skips_audit_recording(
        self, executor: ToolExecutor, audit_store: ToolAuditStore, ids: dict
    ) -> None:
        """When company_id is None, audit store recording is skipped."""

        async def run():
            async def fn(args):
                return "ok"

            await executor.execute(
                agent_id=ids["agent_id"],
                tool_id=ids["tool_id"],
                arguments={"data": "test"},
                execute_fn=fn,
                company_id=None,
            )

        asyncio.run(run())

        records = audit_store.query()
        assert len(records) == 0
