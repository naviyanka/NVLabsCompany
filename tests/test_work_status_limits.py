"""The CEO's work status is bounded in SQL, per company and per bucket.

``work_service.status`` keeps the newest ``OPEN_LIMIT`` open work orders and the newest
``CLOSED_LIMIT`` closed ones. Both queries filter the company and the work-order kind before the
LIMIT, so another company's work orders and ordinary tasks can never crowd out valid work, and
the two buckets never evict each other. Ties break by id, so the answer is deterministic.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

import pytest

from nexus.models.task import Task
from nexus.services import work_service
from nexus.services.work_service import CLOSED_LIMIT, CLOSED_STATUSES, OPEN_LIMIT, SUMMARY_CHARS
from nexus.tools import manager_tools
from tests.test_employee_work import db, w  # noqa: F401 -- fixtures
from tests.test_task_route_security import _sql
from tests.test_work_service import _ctx, co  # noqa: F401 -- fixtures, helpers

pytestmark = pytest.mark.employee_work

BASE = datetime(2026, 1, 1)
OPEN_STATUSES = ("pending", "in_progress", "blocked", "failed", "delegated")
LONG = "r" * (SUMMARY_CHARS * 3)


def _row(company, title, status, minute, serial, *, work=True, result=None):
    """A root task. ``serial`` makes the id (the tie-breaker) predictable."""
    return Task(
        id=uuid.UUID(int=serial),
        company_id=company,
        title=title,
        status=status,
        result=result,
        work_spec={"kind": "work_order"} if work else None,
        created_at=BASE,
        updated_at=BASE + timedelta(minutes=minute),
    )


async def _seed(co, *, mine_open, mine_closed, foreign=40, ordinary=40):
    """Acme's own work first, then rows that are newer than all of it and are not acme's work."""
    rows = []
    serial = 1
    for i in range(mine_open):
        rows.append(_row(co["acme"], f"open-{i}", OPEN_STATUSES[i % 5], i, serial))
        serial += 1
    for i in range(mine_closed):
        status = CLOSED_STATUSES[i % 2]
        done = _row(co["acme"], f"closed-{i}", status, i, serial, result=LONG)
        rows.append(done)
        serial += 1
    top = max(mine_open, mine_closed) + 1
    for i in range(foreign):
        rows.append(_row(co["other"], f"foreign-open-{i}", "in_progress", top + i, serial))
        rows.append(_row(co["other"], f"foreign-closed-{i}", "completed", top + i, serial + 1))
        serial += 2
    for i in range(ordinary):
        rows.append(_row(co["acme"], f"ordinary-{i}", "pending", top + i, serial, work=False))
        serial += 1
    async with co["db"]() as s:
        s.add_all(rows)
        await s.commit()


async def _snapshot(co):
    async with co["db"]() as s:
        return await work_service.status(s, co["acme"])


def _titles(snapshot):
    return [i["title"] for i in snapshot["work"]]


class TestLimits:
    async def test_open_and_closed_buckets_are_independent_and_bounded(self, co):
        await _seed(co, mine_open=OPEN_LIMIT + 7, mine_closed=CLOSED_LIMIT + 5)
        titles = _titles(await _snapshot(co))
        open_n, closed_n = (
            sum(t.startswith("open-") for t in titles),
            sum(t.startswith("closed-") for t in titles),
        )
        assert (open_n, closed_n) == (OPEN_LIMIT, CLOSED_LIMIT)
        assert len(titles) == OPEN_LIMIT + CLOSED_LIMIT

    async def test_the_newest_of_each_bucket_survive(self, co):
        extra_open, extra_closed = 7, 5
        await _seed(co, mine_open=OPEN_LIMIT + extra_open, mine_closed=CLOSED_LIMIT + extra_closed)
        titles = _titles(await _snapshot(co))
        newest_open = [f"open-{i}" for i in range(OPEN_LIMIT + extra_open - 1, extra_open - 1, -1)]
        newest_closed = [
            f"closed-{i}" for i in range(CLOSED_LIMIT + extra_closed - 1, extra_closed - 1, -1)
        ]
        assert titles == newest_open + newest_closed

    async def test_foreign_and_ordinary_rows_cannot_crowd_out_valid_work(self, co):
        # 40 foreign work orders (open and closed) and 40 ordinary tasks, every one newer than
        # acme's own work. A LIMIT applied before the company/kind filter would return only them.
        await _seed(co, mine_open=3, mine_closed=2)
        snapshot = await _snapshot(co)
        assert _titles(snapshot) == ["open-2", "open-1", "open-0", "closed-1", "closed-0"]
        text = json.dumps(snapshot)
        assert "foreign-" not in text and "ordinary-" not in text
        assert str(co["other"]) not in text

    async def test_a_flood_of_open_work_never_evicts_closed_work(self, co):
        await _seed(co, mine_open=OPEN_LIMIT * 3, mine_closed=4)
        titles = _titles(await _snapshot(co))
        assert titles[-4:] == ["closed-3", "closed-2", "closed-1", "closed-0"]
        assert sum(t.startswith("open-") for t in titles) == OPEN_LIMIT

    async def test_a_flood_of_closed_work_never_evicts_open_work(self, co):
        await _seed(co, mine_open=4, mine_closed=CLOSED_LIMIT * 4)
        titles = _titles(await _snapshot(co))
        assert titles[:4] == ["open-3", "open-2", "open-1", "open-0"]
        assert sum(t.startswith("closed-") for t in titles) == CLOSED_LIMIT

    async def test_ties_break_by_id_and_the_answer_is_stable(self, co):
        rows = [_row(co["acme"], f"tie-{n}", "in_progress", 5, n) for n in (9, 3, 7, 1, 5)]
        async with co["db"]() as s:
            s.add_all(rows)
            await s.commit()
        first, second = await _snapshot(co), await _snapshot(co)
        ids = [i["id"] for i in first["work"]]
        assert ids == sorted(ids)
        assert ids == [i["id"] for i in second["work"]]
        assert [i["title"] for i in first["work"]] == ["tie-1", "tie-3", "tie-5", "tie-7", "tie-9"]

    async def test_failed_work_counts_as_open_not_closed(self, co):
        """``failed`` is not in CLOSED_STATUSES: it stays visible with the open bucket."""
        assert "failed" not in CLOSED_STATUSES
        async with co["db"]() as s:
            s.add(_row(co["acme"], "broke", "failed", 1, 1))
            await s.commit()
        assert _titles(await _snapshot(co)) == ["broke"]

    async def test_the_company_and_the_kind_are_filtered_in_sql_before_the_limit(self, co):
        await _seed(co, mine_open=2, mine_closed=2, foreign=3, ordinary=3)
        with _sql(co) as seen:
            await _snapshot(co)
        roots = [
            q for q in seen if "FROM tasks" in q and "LIMIT" in q and "parent_task_id IN" not in q
        ]
        assert len(roots) == 2  # one per bucket
        for query in roots:
            where, _, tail = query.partition("WHERE")[2].partition("ORDER BY")
            assert "tasks.company_id" in where
            assert "tasks.parent_task_id IS NULL" in where and "work_spec" in where
            assert "LIMIT" in tail  # the limit follows the filter, never replaces it


class TestOutputIsBoundedAndAuthorised:
    async def test_the_ceo_tool_returns_a_bounded_company_only_summary(self, co):
        await _seed(co, mine_open=OPEN_LIMIT + 5, mine_closed=CLOSED_LIMIT + 5)
        ceo = _ctx(co["acme"], co["acme_ceo"])
        status = await manager_tools.call(ceo, "ceo_get_work_status", {})
        assert len(status["work"]) == OPEN_LIMIT + CLOSED_LIMIT
        assert _titles(status) == _titles(await _snapshot(co))
        text = json.dumps(status)
        assert "foreign-" not in text and "ordinary-" not in text
        assert str(co["other"]) not in text
        assert "deliverable" not in text
        for item in status["work"]:
            assert item["result"] is None or len(item["result"]) <= SUMMARY_CHARS
        closed = [i for i in status["work"] if i["status"] in CLOSED_STATUSES]
        assert len(closed) == CLOSED_LIMIT
        assert any(i["result"] for i in closed if i["status"] == "completed")
        assert status["counts"] == {
            s: sum(i["status"] == s for i in status["work"]) for s in status["counts"]
        }

    async def test_another_companys_ceo_sees_only_its_own_rows(self, co):
        await _seed(co, mine_open=OPEN_LIMIT + 2, mine_closed=3, foreign=OPEN_LIMIT + 2)
        other = _ctx(co["other"], co["other_ceo"])
        status = await manager_tools.call(other, "ceo_get_work_status", {})
        titles = _titles(status)
        assert titles and all(t.startswith("foreign-") for t in titles)
        assert sum(t.startswith("foreign-open") for t in titles) == OPEN_LIMIT
        assert not any(t.startswith(("open-", "closed-", "ordinary-")) for t in titles)
