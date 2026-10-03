"""The work-order marker: written by one place, read by one predicate, safe on every path.

The marker is ``work_spec == {"kind": "work_order"}`` on a top-level task. ``WorkSpec`` forbids
extra keys, so no public route can write it. Reading goes through
``task_attempts.is_work_order_spec`` (Python) and ``work_service._work_order_clause`` /
``_kind_clause`` (SQL); a test below fails if any other module reads ``kind`` off a work spec.

Semantics, all pinned here:

* exactly ``{"kind": "work_order"}`` on a top-level task is a work order;
* any other ``kind`` (unknown, malformed, wrong type) is never operable as work (the lifecycle
  answers 404) but is still owned by the lifecycle, so the generic routes refuse to move it;
* ``work_spec`` data with no ``kind`` (unrelated JSON) makes a legacy task neither.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import re
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from nexus.models._time import utcnow
from nexus.models.task import Task
from nexus.runtime import orchestrator
from nexus.runtime import task_attempts as ta
from nexus.services import work_service
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import (  # noqa: F401 -- fixtures and helpers
    _code,
    _delegate,
    _get,
    _order,
    _status,
    api,
    co,
)
from tests.test_work_task_route_guards import _plain

pytestmark = pytest.mark.employee_work

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"
LOCKED = "WORK_OWNED_BY_LIFECYCLE"
TEXT_SPEC = {"mode": "text", "objective": "Write it up."}


class TestPublicCallersCannotForgeIt:
    @pytest.mark.parametrize(
        "spec",
        [
            {"kind": "work_order"},
            {"kind": "work_order", **TEXT_SPEC},
            {**TEXT_SPEC, "kind": "work_order"},
            {"kind": "other"},
            {"kind": None},
            {"Kind": "work_order"},
        ],
    )
    async def test_task_routes_reject_any_spec_carrying_a_kind(self, spec, co, api):
        url = f"/api/v1/companies/{co['acme']}/tasks"
        res = await api("POST", url, {"title": "T", "work_spec": spec})
        assert (res.status_code, res.json()["detail"]["code"]) == (422, "INVALID_WORK_SPEC"), spec
        parent = await _plain(co)
        res = await api(
            "POST", f"/api/v1/tasks/{parent}/subtasks", {"title": "S", "work_spec": spec}
        )
        assert (res.status_code, res.json()["detail"]["code"]) == (422, "INVALID_WORK_SPEC"), spec
        stamped = [
            t
            for t in await _rows(co["db"], Task, Task.company_id == co["acme"])
            if t.work_spec and "kind" in t.work_spec
        ]
        assert stamped == []

    def test_the_parser_itself_refuses_a_kind(self):
        for raw in ({"kind": "work_order"}, {**TEXT_SPEC, "kind": "x"}):
            with pytest.raises(Exception) as caught:
                ta.parse_work_spec(raw)
            assert caught.value.detail["code"] == "INVALID_WORK_SPEC"

    async def test_a_real_text_spec_through_the_routes_is_work_but_not_a_work_order(self, co, api):
        url = f"/api/v1/companies/{co['acme']}/tasks"
        res = await api("POST", url, {"title": "T", "work_spec": TEXT_SPEC})
        assert res.status_code == 201, res.text
        task = await _get(co, Task, uuid.UUID(res.json()["id"]))
        assert not work_service.is_work_order(task)
        assert work_service.is_work_spec(task.work_spec)
        async with co["db"]() as s:
            assert not await work_service.is_work_owned(s, co["acme"], task.id)

    async def test_only_the_work_service_creates_the_marker(self, co):
        work = await _order(co)
        task = await _get(co, Task, work)
        assert task.work_spec == {"kind": "work_order"} and task.parent_task_id is None
        assert work_service.is_work_order(task)


class TestPredicate:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ({"kind": "work_order"}, True),
            ({"kind": "work_order", "extra": 1}, True),
            ({"kind": "Work_Order"}, False),
            ({"kind": "work_order "}, False),
            ({"kind": ["work_order"]}, False),
            ({"kind": None}, False),
            ({"kind": {"x": 1}}, False),
            ({"kind": 1}, False),
            ({}, False),
            ({"unrelated": 1}, False),
            (TEXT_SPEC, False),
            ("work_order", False),
            (["work_order"], False),
            (1, False),
            (True, False),
            (None, False),
        ],
    )
    def test_python_predicate_is_strict(self, raw, expected):
        assert ta.is_work_order_spec(raw) is expected

    async def test_a_child_is_never_a_work_order_even_with_the_marker(self, co):
        work = await _order(co)
        child = await _plain(co, parent=work, work_spec={"kind": "work_order"})
        assert not work_service.is_work_order(await _get(co, Task, child))
        async with co["db"]() as s:
            assert await work_service.is_work_owned(s, co["acme"], child)
            assert await _code(work_service.require_work(s, co["acme"], child)) == 404


class TestMarkerIsSafeOnEveryPath:
    async def test_reads_and_attempt_routes_handle_a_stamped_order(self, co, api):
        work = await _order(co)
        await _delegate(co, work)
        got = await api("GET", f"/api/v1/tasks/{work}")
        assert got.status_code == 200 and got.json()["work_spec"] == {"kind": "work_order"}
        listing = await api("GET", f"/api/v1/companies/{co['acme']}/tasks")
        assert listing.status_code == 200
        assert (await api("GET", f"/api/v1/tasks/{work}/attempts")).json() == []
        for method, path in (
            ("POST", f"/api/v1/tasks/{work}/attempts"),
            ("POST", f"/api/v1/tasks/{work}/attempts/{uuid.uuid4()}/retry"),
        ):
            res = await api(method, path, {})
            assert res.status_code in (404, 409, 422), (path, res.text)
            assert res.status_code != 500
        started = await api("POST", f"/api/v1/tasks/{work}/attempts", {})
        assert started.json()["detail"]["code"] == "WORK_ORDER_NOT_EXECUTABLE"
        assert str(work) not in started.text
        assert await _rows(co["db"], ta.TaskAttempt, ta.TaskAttempt.task_id == work) == []

    async def test_the_legacy_stale_reaper_skips_marked_orders_but_reaps_a_legacy_task(self, co):
        work = await _order(co)
        legacy = await _plain(co)
        old = utcnow() - timedelta(days=1)
        async with co["db"]() as s:
            for task_id in (work, legacy):
                task = await s.get(Task, task_id)
                task.status, task.started_at = "in_progress", old
                s.add(task)
            await s.commit()
        async with co["db"]() as s:
            handled = await orchestrator._reap_stale_subtasks(s)
            await s.commit()
        assert handled == 1, "only the legacy task is a stale claim"
        assert (await _get(co, Task, work)).status == "in_progress"
        assert (await _get(co, Task, legacy)).status != "in_progress"

    async def test_live_status_and_the_ceo_tool_handle_the_marker(self, co):
        work = await _order(co)
        snap = await _status(co, work)
        assert snap["work"][0]["id"] == str(work)
        await _delegate(co, work)
        assert (await _get(co, Task, work)).assigned_agent_id == co["acme_lead"]


class TestUnknownAndUnrelatedSpecs:
    async def test_unknown_kind_cannot_be_operated_or_moved(self, co, api):
        task = await _plain(co, work_spec={"kind": "other"})
        before = (await _get(co, Task, task)).status
        res = await api(
            "POST", f"/api/v1/work/{task}/delegate", {"manager_id": str(co["acme_lead"])}
        )
        assert (res.status_code, res.json()["detail"]["code"]) == (422, "TASK_HAS_WORK_SPEC")
        res = await api("POST", f"/api/v1/work/{task}/cancel", {})
        assert res.status_code == 404, res.text
        for method, path, body in (
            ("PUT", f"/api/v1/tasks/{task}/assign", {"agent_id": str(co["acme_bo"])}),
            ("POST", f"/api/v1/tasks/{task}/reassign", {"agent_id": str(co["acme_bo"])}),
            ("PUT", f"/api/v1/tasks/{task}/status", {"status": "completed"}),
            ("POST", f"/api/v1/tasks/{task}/subtasks", {"title": "x"}),
        ):
            res = await api(method, path, body)
            assert res.status_code == 409, (path, res.text)
            assert res.json()["detail"]["code"] in (LOCKED, "WORK_TASK_REQUIRES_VERIFIED_ATTEMPT")
        row = await _get(co, Task, task)
        assert (row.status, row.assigned_agent_id) == (before, None)

    async def test_unrelated_work_data_does_not_turn_a_legacy_task_into_work(self, co, api):
        legacy = await _plain(co, work_spec={"unrelated": "data"})
        child = await _plain(co, parent=legacy)
        for task in (legacy, child):
            for method, path, body in (
                ("PUT", f"/api/v1/tasks/{task}/assign", {"agent_id": str(co["acme_bo"])}),
                ("POST", f"/api/v1/tasks/{task}/reassign", {"agent_id": str(co["acme_lead"])}),
            ):
                assert (await api(method, path, body)).status_code == 200, path
        res = await api("PUT", f"/api/v1/tasks/{legacy}/status", {"status": "completed"})
        assert res.status_code == 200, res.text
        async with co["db"]() as s:
            assert await _code(work_service.require_work(s, co["acme"], legacy)) == 404
            with pytest.raises(Exception) as caught:
                await work_service.delegate_to_manager(
                    s, co["acme"], co["acme_ceo"], co["acme_lead"], legacy, "agent:ceo"
                )
        assert caught.value.status_code in (404, 422)


class TestOneCanonicalPredicate:
    def test_no_module_reads_the_marker_kind_except_the_two_that_own_it(self):
        """A second hand-written check of ``work_spec["kind"]`` would drift from the first."""
        readers = set()
        for path in SRC.rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                code = line.split("#", 1)[0]
                if re.search(r"work_spec", code) and re.search(r"""["']kind["']""", code):
                    readers.add(path.relative_to(SRC).as_posix())
        assert readers <= {"runtime/task_attempts.py", "services/work_service.py"}, readers

    def test_generic_task_routes_and_tools_use_the_service_predicates(self):
        tasks = (SRC / "api/routes/tasks.py").read_text(encoding="utf-8")
        assert "work_service.is_work_owned" in tasks and "work_service.is_work_spec" in tasks
        ceo = (SRC / "tools/ceo_tools.py").read_text(encoding="utf-8")
        assert "work_service.is_work_order(task)" in ceo
        assert "WORK_ORDER_KIND" not in tasks and "work_order" not in tasks
