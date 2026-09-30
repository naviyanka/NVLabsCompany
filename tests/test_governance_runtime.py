"""Governance Studio runtime cancellation, lockdown, isolation and the audit timeline."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlmodel import select

from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import AuditLog
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.services.governance_studio import runtime
from nexus.tools.access import check_tool_access
from tests.test_governance_studio import api  # noqa: F401 -- fixture
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper

WHY = {"reason": "stop this work now"}
LOCK = {"reason": "incident drill", "confirm": "LOCKDOWN"}
UNLOCK = {"reason": "drill is over", "confirm": "RELEASE LOCKDOWN"}


async def _work(factory, t, agent="a") -> dict[str, uuid.UUID]:  # noqa: F811
    """One queued attempt (with its task) and one queued chat turn for ``agent``."""
    async with factory() as db:
        task = Task(company_id=t["acme"], title="work", status="in_progress")
        db.add(task)
        await db.flush()
        attempt = TaskAttempt(
            company_id=t["acme"], task_id=task.id, agent_id=t[agent], attempt_number=1,
            idempotency_key=str(uuid.uuid4()),
        )
        turn = ChatTurn(
            company_id=t["acme"], agent_id=t[agent], session_id=t["s1"], turn_seq=1,
            idempotency_key=str(uuid.uuid4()),
        )
        db.add_all([attempt, turn])
        await db.commit()
    return {"task": task.id, "attempt": attempt.id, "turn": turn.id}


async def _status(factory, model, row_id) -> str:  # noqa: F811
    async with factory() as db:
        return (await db.execute(select(model.status).where(model.id == row_id))).scalar_one()


async def _actions(factory) -> list[str]:  # noqa: F811
    async with factory() as db:
        rows = (await db.execute(select(AuditLog.action).order_by(AuditLog.created_at))).scalars()
        return [a for a in rows.all() if a.startswith("governance.")]


async def _allowed(factory, t, risk="write", agent="a") -> bool:  # noqa: F811
    tool = "manager_delegate_task" if risk == "write" else "ceo_list_managers"
    async with factory() as db:
        return (
            await check_tool_access(
                db, ctx(t, agent=agent), tool_name=tool, default_risk=risk, enforcement="audit"
            )
        ).allowed


class TestActiveWork:
    async def test_lists_ids_and_states_for_this_company_only(self, api, factory, t):  # noqa: F811
        ids = await _work(factory, t)
        body = (await api("GET", "/runtime")).json()
        assert [a["id"] for a in body["attempts"]] == [str(ids["attempt"])]
        assert [x["id"] for x in body["turns"]] == [str(ids["turn"])]
        assert set(body["attempts"][0]) == {
            "id", "task_id", "agent_id", "status", "attempt_number", "cancel_requested",
            "queued_at", "started_at",
        }
        other = (await api("GET", "/runtime", who="outsider")).json()
        assert other == {"attempts": [], "turns": []}
        only_b = (await api("GET", f"/runtime?agent_id={t['b']}")).json()
        assert only_b == {"attempts": [], "turns": []}

    async def test_agents_and_keys_are_refused(self, api, t):  # noqa: F811
        for who in ("run", "key"):
            assert (await api("GET", "/runtime", who=who)).status_code == 403


class TestCancel:
    async def test_cancelling_an_attempt_reuses_the_runtime_and_is_audited(
        self, api, factory, t  # noqa: F811
    ):
        ids = await _work(factory, t)
        r = await api("POST", f"/runtime/attempts/{ids['attempt']}/cancel", WHY)
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        assert await _status(factory, TaskAttempt, ids["attempt"]) == "cancelled"
        assert await _status(factory, Task, ids["task"]) == "pending"
        assert "governance.runtime.cancel_requested" in await _actions(factory)
        again = await api("POST", f"/runtime/attempts/{ids['attempt']}/cancel", WHY)
        assert again.status_code == 200 and again.json()["status"] == "cancelled"

    async def test_cancelling_a_turn(self, api, factory, t):  # noqa: F811
        ids = await _work(factory, t)
        r = await api("POST", f"/runtime/turns/{ids['turn']}/cancel", WHY)
        assert r.status_code == 200 and r.json()["status"] == "cancelled"
        assert await _status(factory, ChatTurn, ids["turn"]) == "cancelled"

    async def test_cancelling_an_agent_leaves_other_agents_alone(self, api, factory, t):  # noqa: F811
        mine, theirs = await _work(factory, t), None
        async with factory() as db:
            task = Task(company_id=t["acme"], title="other", status="in_progress")
            db.add(task)
            await db.flush()
            theirs = TaskAttempt(
                company_id=t["acme"], task_id=task.id, agent_id=t["b"], attempt_number=1,
                idempotency_key="k",
            )
            db.add(theirs)
            await db.commit()
        r = await api("POST", f"/agents/{t['a']}/cancel", WHY)
        assert r.json() == {"cancelled_attempts": 1, "cancelled_turns": 1}
        assert await _status(factory, TaskAttempt, mine["attempt"]) == "cancelled"
        assert await _status(factory, ChatTurn, mine["turn"]) == "cancelled"
        assert await _status(factory, TaskAttempt, theirs.id) == "queued"

    async def test_only_a_human_admin_of_this_company_may_cancel(self, api, factory, t):  # noqa: F811
        ids = await _work(factory, t)
        path = f"/runtime/attempts/{ids['attempt']}/cancel"
        for who in ("viewer", "run", "key"):
            assert (await api("POST", path, WHY, who=who)).status_code == 403, who
        assert (await api("POST", path, WHY, who="outsider")).status_code == 404
        assert (await api("POST", path, {"reason": "no"})).status_code == 422
        assert await _status(factory, TaskAttempt, ids["attempt"]) == "queued"

    async def test_an_unwritable_audit_entry_stops_the_cancel(
        self, api, factory, t, monkeypatch  # noqa: F811
    ):
        ids = await _work(factory, t)

        async def broken(*_a, **_k):
            raise RuntimeError("audit down")

        monkeypatch.setattr(runtime, "audit", broken)
        with pytest.raises(RuntimeError):
            await api("POST", f"/runtime/attempts/{ids['attempt']}/cancel", WHY)
        assert await _status(factory, TaskAttempt, ids["attempt"]) == "queued"


class TestLockdown:
    async def test_it_needs_the_phrase_and_blocks_writes_until_released(
        self, api, factory, t  # noqa: F811
    ):
        assert await _allowed(factory, t)
        wrong = await api("POST", "/lockdown", {**LOCK, "confirm": "yes"})
        assert (wrong.status_code, wrong.json()["detail"]["code"]) == (422, "CONFIRMATION_REQUIRED")
        assert await _allowed(factory, t)

        assert (await api("POST", "/lockdown", LOCK)).status_code == 201
        assert not await _allowed(factory, t)
        assert not await _allowed(factory, t, agent="b")
        assert await _allowed(factory, t, risk="read")
        status = (await api("GET", "/restrictions")).json()
        assert status["lockdown"]["reason"] == "incident drill"
        twice = await api("POST", "/lockdown", LOCK)
        assert (twice.status_code, twice.json()["detail"]["code"]) == (409, "ALREADY_ACTIVE")

        bad = await api("POST", "/lockdown/release", {**UNLOCK, "confirm": "LOCKDOWN"})
        assert bad.status_code == 422 and not await _allowed(factory, t)
        assert (await api("POST", "/lockdown/release", UNLOCK)).status_code == 200
        assert await _allowed(factory, t)
        assert (await api("GET", "/restrictions")).json()["lockdown"] is None
        again = await api("POST", "/lockdown/release", UNLOCK)
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "NOT_ACTIVE")
        assert await _actions(factory) == [
            "governance.lockdown.started", "governance.lockdown.released"
        ]

    async def test_only_a_human_admin_may_start_or_release_it(self, api, factory, t):  # noqa: F811
        for who in ("viewer", "run", "key"):
            assert (await api("POST", "/lockdown", LOCK, who=who)).status_code == 403, who
        await api("POST", "/lockdown", LOCK)
        for who in ("viewer", "run", "key"):
            assert (await api("POST", "/lockdown/release", UNLOCK, who=who)).status_code == 403
        assert not await _allowed(factory, t)

    async def test_lockdown_is_per_company(self, api, factory, t):  # noqa: F811
        await api("POST", "/lockdown", LOCK)
        assert (await api("GET", "/restrictions", who="outsider")).json()["lockdown"] is None
        assert (await api("POST", "/lockdown", LOCK, who="outsider")).status_code == 201
        assert (await api("POST", "/lockdown/release", UNLOCK, who="outsider")).status_code == 200
        assert not await _allowed(factory, t)


class TestIsolation:
    async def test_it_blocks_one_agent_only(self, api, factory, t):  # noqa: F811
        r = await api("POST", f"/agents/{t['a']}/isolate", WHY)
        assert r.status_code == 201 and r.json()["kind"] == "isolation"
        assert not await _allowed(factory, t)
        assert await _allowed(factory, t, agent="b")
        listed = (await api("GET", "/restrictions")).json()["isolated_agents"]
        assert [i["agent_id"] for i in listed] == [str(t["a"])]
        assert (await api("POST", f"/agents/{t['a']}/isolate", WHY)).status_code == 409
        assert (await api("POST", f"/agents/{t['a']}/isolate/release", WHY)).status_code == 200
        assert await _allowed(factory, t)

    async def test_agents_of_other_companies_and_non_admins_are_refused(self, api, t):  # noqa: F811
        assert (await api("POST", f"/agents/{t['foreign']}/isolate", WHY)).status_code == 404
        for who in ("viewer", "run"):
            r = await api("POST", f"/agents/{t['a']}/isolate", WHY, who=who)
            assert r.status_code == 403, who


class TestTimeline:
    async def test_lists_governance_actions_for_this_company(self, api, factory, t):  # noqa: F811
        await api("POST", "/lockdown", LOCK)
        await api("POST", f"/agents/{t['a']}/isolate", WHY)
        items = (await api("GET", "/audit", who="viewer")).json()["items"]
        assert {i["action"] for i in items} == {
            "governance.lockdown.started", "governance.isolation.started"
        }
        assert set(items[0]) == {
            "id", "action", "actor", "resource_type", "resource_id", "details", "at"
        }
        only: list[Any] = (
            await api("GET", "/audit?action=governance.lockdown.started")
        ).json()["items"]
        assert [i["action"] for i in only] == ["governance.lockdown.started"]
        assert (await api("GET", "/audit", who="outsider")).json()["items"] == []
        for who in ("run", "key"):
            assert (await api("GET", "/audit", who=who)).status_code == 403
