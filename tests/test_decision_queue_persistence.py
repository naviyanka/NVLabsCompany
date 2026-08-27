"""Tests for Phase 0.2 governance persistence.

Covers:
- PersistentDecisionQueueManager against a real SQLite database, including
  that queues and items survive a "restart" (a fresh manager over the same DB).
- CostAlertService dedupe state surviving a restart via a state backend.
- BudgetIncident dedupe: one threshold crossing produces one incident.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 — registers every table on SQLModel.metadata
from nexus.governance.budget_enforcer import BudgetDecision, BudgetEnforcer
from nexus.governance.budget_incident import BudgetIncident, BudgetIncidentLog
from nexus.governance.cost_alerting import (
    AlertSeverity,
    AlertThreshold,
    CostAlertService,
)
from nexus.governance.decision_queue_persistent import (
    PersistentDecisionQueueManager,
)
from nexus.governance.redis_state import FileStateBackend


@pytest.fixture
async def session_factory(tmp_path):
    """A session factory over a file-backed SQLite DB with all tables created."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


class TestPersistentDecisionQueue:
    """Tests for the database-backed decision queue manager."""

    async def test_create_queue_returns_uuid(self, session_factory):
        """create_queue persists the queue and returns its id."""
        manager = PersistentDecisionQueueManager(session_factory)
        queue_id = await manager.create_queue("exec-review", uuid.uuid4())

        assert isinstance(queue_id, uuid.UUID)
        assert await manager.list_queues() == ["exec-review"]

    async def test_create_duplicate_queue_raises(self, session_factory):
        """A second queue with the same name is rejected."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("exec-review", uuid.uuid4())

        with pytest.raises(ValueError, match="already exists"):
            await manager.create_queue("exec-review", uuid.uuid4())

    async def test_add_item_to_missing_queue_raises(self, session_factory):
        """Adding to an unknown queue raises KeyError."""
        manager = PersistentDecisionQueueManager(session_factory)

        with pytest.raises(KeyError, match="does not exist"):
            await manager.add_item(
                "nope", uuid.uuid4(), "agent", uuid.uuid4()
            )

    async def test_item_survives_restart(self, session_factory):
        """A queued item is readable by a brand-new manager instance."""
        company_id = uuid.uuid4()
        decision_id = uuid.uuid4()

        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("exec-review", company_id)
        await manager.add_item(
            "exec-review", decision_id, "agent", uuid.uuid4(), priority=1
        )

        # Simulate a process restart: new manager, same database.
        restarted = PersistentDecisionQueueManager(session_factory)
        pending = await restarted.get_pending("exec-review")

        assert len(pending) == 1
        assert pending[0].decision_id == decision_id
        assert pending[0].company_id == company_id
        assert pending[0].status == "pending"

    async def test_get_pending_sorted_by_priority(self, session_factory):
        """Pending items come back ordered by priority ascending."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        for priority in (5, 1, 3):
            await manager.add_item(
                "q", uuid.uuid4(), "agent", uuid.uuid4(), priority=priority
            )

        pending = await manager.get_pending("q")
        assert [item.priority for item in pending] == [1, 3, 5]

    async def test_get_pending_respects_limit(self, session_factory):
        """The limit argument caps the number of rows returned."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        for _ in range(3):
            await manager.add_item("q", uuid.uuid4(), "agent", uuid.uuid4())

        assert len(await manager.get_pending("q", limit=2)) == 2

    async def test_decide_item_persists_outcome(self, session_factory):
        """decide_item stores the outcome and drops the item from pending."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        item = await manager.add_item("q", uuid.uuid4(), "agent", uuid.uuid4())

        await manager.decide_item(item.id, "approved")

        assert await manager.get_pending("q") == []
        restarted = PersistentDecisionQueueManager(session_factory)
        overdue = await restarted.get_overdue("q")
        assert overdue == []

    async def test_snooze_item_persists(self, session_factory):
        """snooze_item moves the item out of pending."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        item = await manager.add_item("q", uuid.uuid4(), "agent", uuid.uuid4())

        until = datetime.now(timezone.utc) + timedelta(hours=1)
        await manager.snooze_item(item.id, until)

        assert await manager.get_pending("q") == []

    async def test_decide_missing_item_raises(self, session_factory):
        """Deciding an unknown item raises KeyError."""
        manager = PersistentDecisionQueueManager(session_factory)

        with pytest.raises(KeyError, match="not found"):
            await manager.decide_item(uuid.uuid4(), "approved")

    async def test_mark_notification_delivered(self, session_factory):
        """mark_notification_delivered flips the flag in the database."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        item = await manager.add_item("q", uuid.uuid4(), "agent", uuid.uuid4())

        await manager.mark_notification_delivered(item.id)

        pending = await manager.get_pending("q")
        assert pending[0].notification_delivered is True

    async def test_get_overdue_returns_past_deadline(self, session_factory):
        """Items past decide_by and still pending are overdue."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        await manager.add_item(
            "q", uuid.uuid4(), "agent", uuid.uuid4(), decide_by=past
        )
        await manager.add_item(
            "q", uuid.uuid4(), "agent", uuid.uuid4(), decide_by=future
        )

        overdue = await manager.get_overdue("q")
        assert len(overdue) == 1

    async def test_get_overdue_unknown_queue_raises(self, session_factory):
        """Filtering overdue by an unknown queue raises KeyError."""
        manager = PersistentDecisionQueueManager(session_factory)

        with pytest.raises(KeyError, match="does not exist"):
            await manager.get_overdue("nope")

    async def test_apply_retention_archives_old_decided(self, session_factory):
        """Decided items older than the retention window are archived."""
        manager = PersistentDecisionQueueManager(session_factory)
        await manager.create_queue("q", uuid.uuid4())
        item = await manager.add_item("q", uuid.uuid4(), "agent", uuid.uuid4())
        await manager.decide_item(item.id, "approved")

        # Nothing is old enough yet.
        assert await manager.apply_retention() == 0

        # Backdate the decision past the 30-day default window.
        await manager._update_item(
            item.id,
            updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
            - timedelta(days=45),
        )
        assert await manager.apply_retention() == 1


class TestCostAlertStatePersistence:
    """Tests for CostAlertService dedupe state across restarts."""

    def _service(self, backend, scope_id):
        enforcer = BudgetEnforcer()
        enforcer.set_budget("agent", scope_id, total_cents=1000)
        service = CostAlertService(enforcer, state_backend=backend)
        service.set_threshold("agent", scope_id, AlertThreshold(80.0, 95.0))
        return enforcer, service

    async def test_state_roundtrip(self, tmp_path):
        """Saved severity and fired alerts reload into a new service."""
        backend = FileStateBackend(tmp_path / "state")
        scope_id = uuid.uuid4()
        enforcer, service = self._service(backend, scope_id)

        enforcer.on_cost_event("agent", scope_id, 850, "spend")
        alerts = service.check_budgets()
        assert len(alerts) == 1
        await service.save_state()

        # Restart: fresh service over the same enforcer state and backend.
        restarted = CostAlertService(enforcer, state_backend=backend)
        restarted.set_threshold("agent", scope_id, AlertThreshold(80.0, 95.0))
        await restarted.load_state()

        fired = restarted.get_fired_alerts()
        assert len(fired) == 1
        assert fired[0].severity == AlertSeverity.WARNING
        assert fired[0].scope == ("agent", scope_id)
        assert fired[0].message == alerts[0].message

    async def test_dedupe_survives_restart(self, tmp_path):
        """The same threshold crossing does not re-fire after a restart."""
        backend = FileStateBackend(tmp_path / "state")
        scope_id = uuid.uuid4()
        enforcer, service = self._service(backend, scope_id)

        enforcer.on_cost_event("agent", scope_id, 850, "spend")
        assert len(service.check_budgets()) == 1
        await service.save_state()

        restarted = CostAlertService(enforcer, state_backend=backend)
        restarted.set_threshold("agent", scope_id, AlertThreshold(80.0, 95.0))
        await restarted.load_state()

        assert restarted.check_budgets() == []

    async def test_load_state_without_saved_data_is_noop(self, tmp_path):
        """load_state on an empty backend leaves the service empty."""
        backend = FileStateBackend(tmp_path / "state")
        scope_id = uuid.uuid4()
        _, service = self._service(backend, scope_id)

        await service.load_state()
        assert service.get_fired_alerts() == []

    async def test_no_backend_is_noop(self):
        """save_state/load_state are no-ops without a backend."""
        scope_id = uuid.uuid4()
        enforcer, service = self._service(None, scope_id)

        await service.save_state()
        await service.load_state()
        assert service.get_fired_alerts() == []


class TestBudgetIncidentDedupe:
    """Tests for the (company/scope, threshold_type) incident dedupe key."""

    def test_same_key_recorded_once(self):
        """A second incident with the same dedupe key is dropped."""
        log = BudgetIncidentLog()
        scope_id = uuid.uuid4()
        key = BudgetIncident.build_dedupe_key("agent", scope_id, "cost_cents")

        assert log.record(BudgetIncident(scope_id=scope_id, dedupe_key=key))
        assert not log.record(BudgetIncident(scope_id=scope_id, dedupe_key=key))
        assert len(log.get_all()) == 1

    def test_different_threshold_types_both_recorded(self):
        """Distinct threshold types are separate incidents."""
        log = BudgetIncidentLog()
        scope_id = uuid.uuid4()

        log.record(
            BudgetIncident(
                dedupe_key=BudgetIncident.build_dedupe_key(
                    "agent", scope_id, "cost_cents"
                )
            )
        )
        log.record(
            BudgetIncident(
                dedupe_key=BudgetIncident.build_dedupe_key(
                    "agent", scope_id, "tokens"
                )
            )
        )

        assert len(log.get_all()) == 2

    def test_incidents_without_key_are_not_deduped(self):
        """Legacy callers passing no dedupe key keep appending."""
        log = BudgetIncidentLog()
        log.record(BudgetIncident())
        log.record(BudgetIncident())

        assert len(log.get_all()) == 2

    def test_clear_dedupe_key_allows_refire(self):
        """Clearing a key lets a later crossing record a fresh incident."""
        log = BudgetIncidentLog()
        key = BudgetIncident.build_dedupe_key(
            "agent", uuid.uuid4(), "cost_cents"
        )

        log.record(BudgetIncident(dedupe_key=key))
        log.clear_dedupe_key(key)
        log.record(BudgetIncident(dedupe_key=key))

        assert len(log.get_all()) == 2

    def test_repeated_crossing_produces_one_incident(self):
        """Re-checking one breached budget yields a single incident."""
        scope_id = uuid.uuid4()
        enforcer = BudgetEnforcer(hard_stop_enabled=True)
        enforcer.set_budget("agent", scope_id, total_cents=1000)

        assert (
            enforcer.on_cost_event("agent", scope_id, 1100, "over")
            == BudgetDecision.DENIED
        )
        assert (
            enforcer.on_cost_event("agent", scope_id, 50, "still over")
            == BudgetDecision.DENIED
        )

        assert len(enforcer.incident_log.get_all()) == 1
