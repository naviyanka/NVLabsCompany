"""Agent and Goal routes on a real, migrated PostgreSQL database under row-level security.

The real app signs two companies in. Company A's people try company B's agents and goals, and
references to them, through the real routes. Every attempt must look like a missing row, change
nothing, and leave no row or audit residue. Only seeding and read-back use the migration role.
"""

# ruff: noqa: F811 -- fixtures imported from the PostgreSQL integration modules
from __future__ import annotations

import uuid

import pytest
from sqlmodel import select

from nexus.models.agent import Agent
from nexus.models.task import Goal
from tests.test_postgres_integration import (  # noqa: F401 -- module fixtures
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
    system_user_postgres_url,
)
from tests.test_work_execution_postgres import Stack, stack  # noqa: F401 -- fixtures

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


async def _goal(stack, company, title="Grow", **fields) -> uuid.UUID:
    async with stack.admin_db() as s:
        goal = Goal(company_id=company, title=title, **fields)
        s.add(goal)
        await s.commit()
        return goal.id


async def _audits(stack, *companies) -> int:
    return await stack.scalar(
        "select count(*) from audit_log where company_id = any(:c)", c=list(companies)
    )


async def _goals(stack, company) -> int:
    return len(await stack.rows(Goal, Goal.company_id == company))


def _spellings(company: uuid.UUID) -> list[str]:
    return [str(company), company.hex, f"urn:uuid:{company}"]


class TestAgentsAcrossTenants:
    async def test_foreign_agents_cannot_be_read_changed_or_removed(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        before = await _audits(stack, a["company"], b["company"])
        absent = uuid.uuid4()
        calls = (
            ("PUT", "/api/v1/agents/{}", {"name": "pwned"}),
            ("PATCH", "/api/v1/agents/{}", {"name": "pwned"}),
            ("DELETE", "/api/v1/agents/{}", None),
            ("POST", "/api/v1/agents/{}/pause", None),
            ("POST", "/api/v1/agents/{}/wake", None),
        )
        for method, path, body in calls:
            foreign = await admin.call(method, path.format(b["eve"]), body)
            missing = await admin.call(method, path.format(absent), body)
            assert foreign.status_code == missing.status_code == 404, (method, path)
            # The message echoes the id the caller asked for; nothing else may differ.
            echoed = foreign.text.replace(str(b["eve"]), str(absent))
            assert echoed == missing.text, (method, path)
        row = await stack.one(Agent, b["eve"])
        assert row is not None and row.name == "eve" and row.status == "idle"
        assert await _audits(stack, a["company"], b["company"]) == before

    async def test_a_foreign_company_path_is_denied_like_a_missing_company(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        for spelling in [*_spellings(b["company"]), str(uuid.uuid4())]:
            reply = await admin.call(
                "PATCH", f"/api/v1/companies/{spelling}/agents/{b['eve']}", {"name": "pwned"}
            )
            assert reply.status_code == 403, spelling
        assert (await stack.one(Agent, b["eve"])).name == "eve"

    async def test_foreign_company_reads_match_a_missing_company_in_every_spelling(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        for spelling in [*_spellings(b["company"]), str(uuid.uuid4())]:
            for path in (
                f"/api/v1/companies/{spelling}/agents",
                f"/api/v1/companies/{spelling}/agents/{b['eve']}",
                f"/api/v1/companies/{spelling}/agents/{a['eve']}",
            ):
                reply = await admin.call("GET", path)
                assert reply.status_code == 403, path
                assert str(b["eve"]) not in reply.text and str(a["eve"]) not in reply.text
        own = await admin.call("GET", f"/api/v1/companies/{a['company'].hex}/agents")
        assert own.status_code == 200
        assert str(a["eve"]) in {x["id"] for x in own.json()}
        assert {x["company_id"] for x in own.json()} == {str(a["company"])}
        assert (
            await admin.call("GET", f"/api/v1/companies/{a['company']}/agents/{b['eve']}")
        ).status_code == 404

    async def test_only_a_company_admin_changes_authority_and_nothing_leaks(self, stack):
        a = await stack.seed("A")
        viewer, admin = await stack.login(a["viewer"]), await stack.login(a["admin"])
        before = await _audits(stack, a["company"])
        for body in ({"name": "x"}, {"role": "ceo"}, {"autonomy_policy": "high"}):
            denied = await viewer.call("PATCH", f"/api/v1/agents/{a['eve']}", body)
            assert denied.status_code == 403, body
        unknown = await admin.call("PATCH", f"/api/v1/agents/{a['eve']}", {"is_ceo": True})
        assert unknown.status_code == 422
        row = await stack.one(Agent, a["eve"])
        assert (row.name, row.role, row.is_ceo) == ("eve", "analyst", False)
        assert await _audits(stack, a["company"]) == before
        # Positive control: the admin's own change goes through.
        ok = await admin.call("PATCH", f"/api/v1/agents/{a['eve']}", {"name": "eve2"})
        assert ok.status_code == 200 and (await stack.one(Agent, a["eve"])).name == "eve2"


class TestGoalsAcrossTenants:
    async def test_foreign_goals_cannot_be_read_changed_removed_or_run(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        theirs = await _goal(stack, b["company"])
        before = await _audits(stack, a["company"], b["company"])
        absent = uuid.uuid4()
        calls = (
            ("GET", "/api/v1/goals/{}", None),
            ("PUT", "/api/v1/goals/{}", {"title": "pwned"}),
            ("DELETE", "/api/v1/goals/{}", None),
            ("POST", "/api/v1/goals/{}/execute", None),
        )
        for method, path, body in calls:
            foreign = await admin.call(method, path.format(theirs), body)
            missing = await admin.call(method, path.format(absent), body)
            assert foreign.status_code == missing.status_code == 404, (method, path)
            assert foreign.json() == missing.json(), (method, path)
        row = await stack.one(Goal, theirs)
        assert (row.title, row.status) == ("Grow", "active")
        assert await _audits(stack, a["company"], b["company"]) == before

    async def test_foreign_company_paths_match_a_missing_company_in_every_spelling(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        paths = ("/api/v1/companies/{}/goals", "/api/v1/companies/{}/goals/stats")
        for path in paths:
            outcomes = {
                (await admin.call("GET", path.format(s))).status_code
                for s in [*_spellings(b["company"]), str(uuid.uuid4())]
            }
            assert outcomes == {403}, path
        made = await admin.call(
            "POST", f"/api/v1/companies/{b['company'].hex}/goals", {"title": "planted"}
        )
        assert made.status_code == 403
        assert await _goals(stack, b["company"]) == 0 and await _goals(stack, a["company"]) == 0

    async def test_references_to_foreign_rows_look_missing_and_leave_no_goal(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        url = f"/api/v1/companies/{a['company']}/goals"
        foreign_parent = await _goal(stack, b["company"])
        before = await _audits(stack, a["company"], b["company"])
        for field, foreign, code in (
            ("parent_id", foreign_parent, "GOAL_NOT_FOUND"),
            ("owner_agent_id", b["eve"], "AGENT_NOT_FOUND"),
        ):
            theirs = await admin.call("POST", url, {"title": "t", field: str(foreign)})
            absent = await admin.call("POST", url, {"title": "t", field: str(uuid.uuid4())})
            assert theirs.status_code == absent.status_code == 404, field
            assert theirs.json() == absent.json(), field
            assert theirs.json()["detail"]["code"] == code
        assert await _goals(stack, a["company"]) == 0
        assert await _audits(stack, a["company"], b["company"]) == before

    async def test_ineligible_owner_and_closed_parent_are_stable_conflicts(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        url = f"/api/v1/companies/{a['company']}/goals"
        async with stack.admin_db() as s:
            eve = (await s.execute(select(Agent).where(Agent.id == a["eve"]))).scalar_one()
            eve.status = "paused"
            await s.commit()
        closed = await _goal(stack, a["company"], status="completed")
        owner = await admin.call("POST", url, {"title": "t", "owner_agent_id": str(a["eve"])})
        parent = await admin.call("POST", url, {"title": "t", "parent_id": str(closed)})
        assert (owner.status_code, owner.json()["detail"]["code"]) == (409, "AGENT_NOT_ASSIGNABLE")
        assert (parent.status_code, parent.json()["detail"]["code"]) == (409, "GOAL_CLOSED")
        assert await _goals(stack, a["company"]) == 1  # only the seeded closed goal

    async def test_viewer_cannot_write_and_a_terminal_goal_stays_closed(self, stack):
        a = await stack.seed("A")
        viewer, admin = await stack.login(a["viewer"]), await stack.login(a["admin"])
        goal = await _goal(stack, a["company"])
        done = await _goal(stack, a["company"], title="Done", status="completed")
        before = await _audits(stack, a["company"])
        url = f"/api/v1/companies/{a['company']}/goals"
        assert (await viewer.call("POST", url, {"title": "t"})).status_code == 403
        assert (
            await viewer.call("PUT", f"/api/v1/goals/{goal}", {"title": "x"})
        ).status_code == 403
        assert (await viewer.call("DELETE", f"/api/v1/goals/{goal}")).status_code == 403
        assert (await viewer.call("POST", f"/api/v1/goals/{goal}/execute")).status_code == 403
        assert (await viewer.call("GET", url)).status_code == 200
        reopen = await admin.call("PUT", f"/api/v1/goals/{done}", {"status": "active"})
        assert (reopen.status_code, reopen.json()["detail"]["code"]) == (409, "GOAL_CLOSED")
        assert (await stack.one(Goal, goal)).title == "Grow"
        assert (await stack.one(Goal, done)).status == "completed"
        assert await _audits(stack, a["company"]) == before
        # Positive control: the admin's own create and update go through.
        made = await admin.call("POST", url, {"title": "Mine"})
        assert made.status_code == 201
        edit = await admin.call("PUT", f"/api/v1/goals/{goal}", {"title": "Grow more"})
        assert edit.status_code == 200 and (await stack.one(Goal, goal)).title == "Grow more"
