"""A temporary allow lifts a default deny only. Role and business invariants still apply.

Runs on the Manager Core fixtures. Each test gives the agent an approved temporary allow for
the exact tool, then drives the real entry point (``guarded_call`` over ``manager_tools.call``,
or the hiring route) and shows the tool's own rule still refuses.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from nexus.governance.approval_signing import HIGH_RISK_SPEND_CENTS
from nexus.models.governance_studio import GovernanceTempAccess
from nexus.tools import manager_tools
from nexus.tools.factory import guarded_call
from tests.test_employee_work import db, w  # noqa: F401 -- fixtures
from tests.test_manager_core import _ctx, _delegate, _report_to, team  # noqa: F401 -- fixtures
from tests.test_manager_hiring import AUTO, _employees, _hire, _policy, h  # noqa: F401

pytestmark = pytest.mark.employee_work


async def _allow_grant(db, company, agent, tool, **over):  # noqa: F811
    now = datetime.now(UTC).replace(tzinfo=None)
    fields = dict(
        company_id=company, agent_id=agent, effect="allow", tool_name=tool, risk_level="write",
        status="active", expires_at=now + timedelta(hours=1), requested_by="a", approved_by="b",
    )
    async with db() as s:
        grant = GovernanceTempAccess(**{**fields, **over})
        s.add(grant)
        await s.commit()
        return grant.id


async def _through_guard(team, agent, tool, args):  # noqa: F811
    ctx = _ctx(team["acme"], agent)

    async def run():
        return await manager_tools.call(ctx, tool, args)

    return await guarded_call(ctx, tool, args, run, source="test", default_risk="write")


class TestRoleInvariants:
    async def test_grant_does_not_make_a_manager_the_ceo(self, db, team):  # noqa: F811
        await _allow_grant(db, team["acme"], team["lead"], "ceo_record_decision")
        with pytest.raises(HTTPException) as err:
            await _through_guard(team, team["lead"], "ceo_record_decision", {"content": "x"})
        assert err.value.detail["code"] == "NOT_CEO"

    async def test_grant_does_not_reach_another_managers_report(self, db, team):  # noqa: F811
        assert (await _report_to(team, team["acme_claude"], team["lead"])).status_code == 200
        await _allow_grant(db, team["acme"], team["lead"], "manager_delegate_task")
        args = {"task_id": str(team["task2"]), "employee_id": str(team["claude2"])}
        with pytest.raises(HTTPException) as err:
            await _through_guard(team, team["lead"], "manager_delegate_task", args)
        assert err.value.detail["code"] == "NOT_A_DIRECT_REPORT"
        # The same grant still serves a real direct report.
        ok = await _delegate(team, team["task2"], team["acme_claude"])
        assert ok.status_code in (200, 201), ok.text


class TestHiringInvariants:
    async def test_grant_stands_in_for_the_allow_policy_and_nothing_more(self, db, h):  # noqa: F811
        await _allow_grant(db, h["acme"], h["lead"], "manager_request_hire")
        await _policy(db, h, **AUTO, max_recurring_monthly_cents=699)
        view = (await _hire(h)).json()
        codes = [r["code"] for r in view["policy_reasons"]]
        assert view["status"] == "rejected"
        assert codes == ["RECURRING_BUDGET_EXCEEDED"], "the tool was allowed; the budget rule held"
        assert await _employees(db, h) == []

    async def test_grant_does_not_skip_the_hiring_budget(self, db, h):  # noqa: F811
        await _allow_grant(db, h["acme"], h["lead"], "manager_request_hire")
        await _policy(db, h, **AUTO, hiring_budget_monthly_cents=499)
        view = (await _hire(h)).json()
        assert view["status"] == "rejected"
        assert "HIRING_BUDGET_EXCEEDED" in [r["code"] for r in view["policy_reasons"]]

    async def test_grant_does_not_replace_the_signature_quorum(self, db, h):  # noqa: F811
        await _allow_grant(db, h["acme"], h["lead"], "manager_request_hire")
        await _policy(db, h, auto_approve={"enabled": True, "max_monthly_cents": 10**9,
                                           "max_one_time_cents": 10**9})
        view = (await _hire(h, estimated_one_time_cents=HIGH_RISK_SPEND_CENTS)).json()
        assert view["status"] == "approval_required"
        assert await _employees(db, h) == []

    async def test_without_the_grant_the_same_request_is_refused_for_the_tool(self, db, h):  # noqa: F811
        await _policy(db, h, **AUTO)
        view = (await _hire(h)).json()
        assert [r["code"] for r in view["policy_reasons"]] == ["TOOL_POLICY_DENIED"]

    async def test_an_unapproved_grant_does_not_allow_hiring(self, db, h):  # noqa: F811
        await _allow_grant(db, h["acme"], h["lead"], "manager_request_hire",
                           approved_by=None, approval_id=uuid.uuid4())
        await _policy(db, h, **AUTO)
        view = (await _hire(h)).json()
        assert [r["code"] for r in view["policy_reasons"]] == ["TOOL_POLICY_DENIED"]
