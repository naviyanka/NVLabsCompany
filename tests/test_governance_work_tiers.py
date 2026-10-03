"""Which governance tier grants each company-work tool, and that every layer agrees.

Layers compared: the runtime ``check_tool_access`` (ToolPolicy), the Governance Studio catalogue
(``explicit_allow_required``), the effective-access simulator and the autonomy presets.

Expected grants (the preset a tool first appears in; every higher preset keeps it):

* level 0 advisory: ``ceo_get_work_status`` (read; CEO only, so only an agent that is the CEO)
* level 3 delegated autonomy: ``manager_delegate_task``, ``manager_assign_work``,
  ``manager_review_work`` (manager designation, so only an agent with a direct report)
* level 4 operational autonomy: ``manager_request_hire``
* level 5 restricted executive autonomy: ``ceo_create_goal_or_work_order``,
  ``ceo_delegate_task_to_manager`` (CEO only)

``manager_assign_work`` and ``manager_review_work`` are explicit-allow-only: assigning starts a
model run and reviewing decides a deliverable, so no profile default, wildcard or risk rule may
grant them. A ToolPolicy that names the tool does.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import pytest

from nexus.services.governance_studio import catalog
from nexus.tools.access import EXPLICIT_ALLOW_ONLY, check_tool_access
from tests.test_governance_presets import _draft, _make, _publish
from tests.test_governance_studio import _eff, _policy, api  # noqa: F401 -- fixtures, helpers
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures

WORK_TOOLS = ("manager_delegate_task", "manager_assign_work", "manager_review_work")
MANAGER_TOOLS = WORK_TOOLS
FIRST_LEVEL = {
    "ceo_get_work_status": 0,
    "manager_delegate_task": 3,
    "manager_assign_work": 3,
    "manager_review_work": 3,
    "manager_request_hire": 4,
    "ceo_create_goal_or_work_order": 5,
    "ceo_delegate_task_to_manager": 5,
}
PRESETS = (
    "advisory",
    "assisted",
    "task_autonomy",
    "delegated_autonomy",
    "operational_autonomy",
    "restricted_executive_autonomy",
)


async def _runtime(factory, t, tool):  # noqa: F811
    async with factory() as db:
        decision = await check_tool_access(
            db, ctx(t), tool_name=tool, default_risk="write", enforcement="enforce"
        )
    return decision.allowed


def _by_tool(tool):
    return next(c for c in catalog.build_catalog() if c["tool_name"] == tool)


class TestExplicitAllowOnly:
    def test_catalogue_and_runtime_set_agree(self):
        for tool in WORK_TOOLS:
            assert tool in EXPLICIT_ALLOW_ONLY
            assert _by_tool(tool)["explicit_allow_required"] is True
        for cap in catalog.build_catalog():
            assert cap["explicit_allow_required"] == (cap["tool_name"] in EXPLICIT_ALLOW_ONLY)

    async def test_nothing_implicit_grants_them_and_runtime_equals_simulator(
        self,
        factory,
        t,  # noqa: F811
    ):
        """No policy, a wildcard allow, a risk-level allow and a catch-all allow all stay denied."""
        eff = await _eff(factory, t)
        for tool in WORK_TOOLS:
            assert eff[f"org.{tool}"]["state"] == "denied", tool
            assert not await _runtime(factory, t, tool)
        for index, conditions in enumerate(
            ({"tool_name": ["manager_*"]}, {"risk_level": ["write"]}, {}, {"tool_name": ["*"]})
        ):
            await _policy(
                factory,
                t["acme"],
                name=f"broad-{index}",
                effect="allow",
                priority=index + 1,
                conditions=conditions,
            )
        eff = await _eff(factory, t)
        for tool in WORK_TOOLS:
            assert eff[f"org.{tool}"]["state"] == "denied", tool
            assert not await _runtime(factory, t, tool)

    async def test_naming_the_tool_grants_it_and_a_deny_still_wins(self, factory, t):  # noqa: F811
        await _policy(
            factory,
            t["acme"],
            name="allow review",
            effect="allow",
            priority=10,
            conditions={"tool_name": ["manager_review_work"]},
        )
        eff = await _eff(factory, t)
        assert eff["org.manager_review_work"]["state"] == "allowed"
        assert await _runtime(factory, t, "manager_review_work")
        assert eff["org.manager_assign_work"]["state"] == "denied"
        await _policy(
            factory,
            t["acme"],
            name="freeze review",
            effect="deny",
            priority=1,
            conditions={"tool_name": ["manager_review_work"]},
        )
        eff = await _eff(factory, t)
        assert eff["org.manager_review_work"]["state"] == "denied"
        assert not await _runtime(factory, t, "manager_review_work")


class TestDelegateTaskIsExplicitAllowOnly:
    """``manager_delegate_task`` hands a task to another agent and queues its run."""

    async def test_default_wildcard_named_allow_and_deny_agree_with_the_simulator(
        self,
        factory,
        t,  # noqa: F811
    ):
        tool = "manager_delegate_task"
        assert tool in EXPLICIT_ALLOW_ONLY
        assert _by_tool(tool)["explicit_allow_required"] is True
        assert (await _eff(factory, t))[f"org.{tool}"]["state"] == "denied"
        assert not await _runtime(factory, t, tool)
        await _policy(
            factory,
            t["acme"],
            name="wild",
            effect="allow",
            priority=5,
            conditions={"tool_name": ["manager_*"]},
        )
        assert (await _eff(factory, t))[f"org.{tool}"]["state"] == "denied"
        assert not await _runtime(factory, t, tool)
        await _policy(
            factory,
            t["acme"],
            name="named",
            effect="allow",
            priority=10,
            conditions={"tool_name": [tool]},
        )
        assert (await _eff(factory, t))[f"org.{tool}"]["state"] == "allowed"
        assert await _runtime(factory, t, tool)
        await _policy(
            factory,
            t["acme"],
            name="freeze",
            effect="deny",
            priority=1,
            conditions={"tool_name": [tool]},
        )
        assert (await _eff(factory, t))[f"org.{tool}"]["state"] == "denied"
        assert not await _runtime(factory, t, tool)

    async def test_a_stock_write_tool_is_still_allowed_by_default(self, factory, t):  # noqa: F811
        """The probe the older governance tests use: not explicit-only, so a default allows it."""
        assert "msg-slack-send" not in EXPLICIT_ALLOW_ONLY
        async with factory() as db:
            decision = await check_tool_access(
                db, ctx(t), tool_name="msg-slack-send", default_risk="write", enforcement="audit"
            )
        assert decision.allowed


class TestPresetTiers:
    async def test_each_preset_grants_exactly_the_documented_tools(self, api, factory, t):  # noqa: F811
        await _make(factory, t, ceo=True, report=True)
        for key in PRESETS:
            draft = (await _draft(api, t, key)).json()
            allowed = {
                n
                for r in draft["rules"]
                if r["effect"] == "allow"
                for n in r["conditions"]["tool_name"]
            }
            denied = {
                n
                for r in draft["rules"]
                if r["effect"] == "deny"
                for n in r["conditions"]["tool_name"]
            }
            level = PRESETS.index(key)
            for tool, first in FIRST_LEVEL.items():
                assert (tool in allowed) == (level >= first), (key, tool)
                assert (tool in denied) == (level < first), (key, tool)

    async def test_a_manager_who_is_not_ceo_never_holds_ceo_write_tools(self, api, factory, t):  # noqa: F811
        await _make(factory, t, ceo=False, report=True)
        draft = (await _draft(api, t, "operational_autonomy")).json()
        allowed = {
            n
            for r in draft["rules"]
            if r["effect"] == "allow"
            for n in r["conditions"]["tool_name"]
        }
        assert set(MANAGER_TOOLS) <= allowed
        assert not {n for n in allowed if n.startswith("ceo_")}
        assert (await _draft(api, t, "restricted_executive_autonomy")).status_code == 409

    async def test_an_agent_without_reports_holds_no_manager_tool_at_any_level(
        self,
        api,
        factory,
        t,  # noqa: F811
    ):
        for key in ("advisory", "assisted", "task_autonomy"):
            draft = (await _draft(api, t, key)).json()
            allowed = {
                n
                for r in draft["rules"]
                if r["effect"] == "allow"
                for n in r["conditions"]["tool_name"]
            }
            assert not {n for n in allowed if n.startswith(("manager_", "ceo_"))}, key
        for key in ("delegated_autonomy", "operational_autonomy"):
            assert (await _draft(api, t, key)).status_code == 409


class TestRuntimeCatalogueSimulatorAndPresetsAgree:
    @pytest.mark.parametrize("key", ["task_autonomy", "delegated_autonomy"])
    async def test_published_preset_is_seen_the_same_by_every_layer(
        self,
        key,
        api,
        factory,
        t,  # noqa: F811
    ):
        await _make(factory, t, ceo=False, report=True)
        draft = (await _draft(api, t, key)).json()
        await _publish(api, draft["draft"])
        eff = await _eff(factory, t)
        granted = PRESETS.index(key) >= 3
        for tool in MANAGER_TOOLS:
            seen = eff[f"org.{tool}"]["state"] in ("allowed", "inherited")
            assert seen == granted, (key, tool, "simulator")
            assert await _runtime(factory, t, tool) == granted, (key, tool, "runtime")
        promised = {c["capability_id"]: c["after"] for c in draft["capability_diff"]["changes"]}
        for tool in WORK_TOOLS:
            assert promised.get(f"org.{tool}", "allow" if granted else "deny") == (
                "allow" if granted else "deny"
            )
