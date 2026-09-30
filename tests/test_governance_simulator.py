"""Governance Studio simulator and deterministic risk rules."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func
from sqlmodel import select

from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernanceRestriction, GovernanceTempAccess
from nexus.models.secret import Secret, SecretBinding
from nexus.models.tool import ToolPolicy
from nexus.services.governance_studio import catalog, risk
from nexus.tools.access import check_tool_access
from tests.test_governance_studio import api  # noqa: F401 -- fixture
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper

HIRE = "org.ceo_request_hire"
ALLOW_HIRE = {
    "name": "allow hire",
    "effect": "allow",
    "conditions": {
        "tool_name": ["ceo_request_hire"],
        "governance": {"owner": "coo", "review_by": "2027-01-01"},
    },
}


async def sim(api, t, cap=HIRE, who="admin", **extra):  # noqa: F811
    body = {"agent_id": str(t["a"]), "capability_id": cap, **extra}
    return await api("POST", "/simulate", body, who=who)


def codes(body) -> set[str]:
    return {f["code"] for f in body["findings"]}


def _grant(t, **over) -> GovernanceTempAccess:  # noqa: F811
    now = datetime.now(UTC).replace(tzinfo=None)
    fields = dict(
        company_id=t["acme"], agent_id=t["a"], effect="allow", tool_name="ceo_request_hire",
        status="active", expires_at=now + timedelta(hours=1), requested_by="x", approved_by="y",
    )
    return GovernanceTempAccess(**{**fields, **over})


class TestSimulate:
    async def test_live_decision_and_no_proposal(self, api, t):  # noqa: F811
        body = (await sim(api, t)).json()
        assert body["simulated"] and body["proposed"] is None
        assert (body["current"]["state"], body["current"]["code"]) == ("denied", "DEFAULT_DENY")
        assert "arguments" not in body

    async def test_proposed_rules_change_only_the_proposed_decision(self, api, t):  # noqa: F811
        body = (await sim(api, t, proposed_rules=[ALLOW_HIRE])).json()
        assert body["current"]["decision"] == "deny"
        assert (body["proposed"]["state"], body["proposed"]["source"]) == (
            "allowed",
            "policy:allow hire",
        )

    @pytest.mark.parametrize(
        "rules",
        [
            [],
            [ALLOW_HIRE],
            [{"name": "deny writes", "effect": "deny", "conditions": {"risk_level": ["write"]}},
             ALLOW_HIRE],
            [{"name": "allow all", "effect": "allow", "conditions": {}}],
        ],
    )
    async def test_proposal_matches_the_runtime_once_applied(
        self, api, factory, t, rules  # noqa: F811
    ):
        caps = ("org.ceo_request_hire", "org.ceo_list_managers", "tool.http-request")
        shown = {c: (await sim(api, t, c, proposed_rules=rules)).json()["proposed"] for c in caps}
        async with factory() as db:
            for r in rules:
                db.add(ToolPolicy(company_id=t["acme"], **r))
            await db.commit()
        for cap in catalog.build_catalog():
            if cap["id"] not in shown:
                continue
            async with factory() as db:
                d = await check_tool_access(
                    db, ctx(t), tool_name=cap["tool_name"], default_risk=cap["risk"],
                    enforcement="audit",
                )
            assert (shown[cap["id"]]["decision"] == "allow") == d.allowed, cap["id"]

    async def test_restriction_and_session_grant_are_seen(self, api, factory, t):  # noqa: F811
        async with factory() as db:
            db.add(_grant(t, session_id=t["s1"]))
            await db.commit()
        assert (await sim(api, t)).json()["current"]["decision"] == "deny"
        inside = (await sim(api, t, session_id=str(t["s1"]))).json()["current"]
        assert inside["state"] == "temporarily_allowed"
        async with factory() as db:
            db.add(GovernanceRestriction(company_id=t["acme"], scope="company", kind="lockdown",
                                         reason="drill", created_by="x"))
            await db.commit()
        locked = (await sim(api, t, session_id=str(t["s1"]))).json()["current"]
        assert (locked["state"], locked["code"]) == ("denied", "RESTRICTION_ACTIVE")

    async def test_it_changes_nothing(self, api, factory, t):  # noqa: F811
        async with factory() as db:
            db.add(_grant(t, max_uses=1))
            await db.commit()

        async def counts():
            async with factory() as db:
                rows = [
                    (await db.execute(select(func.count()).select_from(m))).scalar_one()
                    for m in (GovernanceTempAccess, AuditLog, ToolPolicy)
                ]
                used = (await db.execute(select(GovernanceTempAccess.used_count))).scalar_one()
                return rows, used

        before = await counts()
        for _ in range(3):
            assert (await sim(api, t, proposed_rules=[ALLOW_HIRE])).status_code == 200
        assert await counts() == before
        assert before[1] == 0

    async def test_access_and_bounds(self, api, t):  # noqa: F811
        for who in ("run", "key"):
            assert (await sim(api, t, who=who)).status_code == 403
        assert (await sim(api, t, who="viewer")).status_code == 200
        assert (await sim(api, t, who="outsider")).status_code == 404
        assert (await sim(api, t, cap="nope")).json()["detail"]["code"] == "CAPABILITY_NOT_FOUND"
        bad_session = await sim(api, t, session_id=str(uuid.uuid4()))
        assert bad_session.json()["detail"]["code"] == "SESSION_NOT_FOUND"
        bad_rule = {"name": "x", "effect": "allow", "conditions": {"script": "rm -rf"}}
        assert (await sim(api, t, proposed_rules=[bad_rule])).status_code == 422
        too_many = [{"name": f"r{i}", "effect": "deny"} for i in range(101)]
        assert (await sim(api, t, proposed_rules=too_many)).status_code == 422


class TestRiskRules:
    def test_a_broad_allow_is_flagged_until_it_names_its_owner_and_review(self):
        broad = {"name": "all", "effect": "allow", "conditions": {}}
        assert {f["code"] for f in risk.rule_findings([broad])} == {
            "WILDCARD_HIGH_RISK",
            "NO_OWNER_OR_REVIEW_DATE",
        }
        named = {"name": "n", "effect": "allow", "conditions": {"tool_name": ["ceo_request_hire"]}}
        assert [f["code"] for f in risk.rule_findings([named])] == ["NO_OWNER_OR_REVIEW_DATE"]
        assert risk.rule_findings([ALLOW_HIRE]) == []
        reads = {"name": "r", "effect": "allow", "conditions": {"risk_level": ["read"]}}
        deny = {"name": "d", "effect": "deny", "conditions": {}}
        assert risk.rule_findings([reads, deny]) == []

    def test_the_author_may_not_review_their_own_change(self):
        found = risk.rule_findings([], author="a@x", reviewers=["b@x", "a@x"])
        assert [f["code"] for f in found] == ["SELF_REVIEW"]
        assert risk.rule_findings([], author="a@x", reviewers=["b@x"]) == []

    @pytest.mark.parametrize(
        ("tags", "code"),
        [
            (({"pr_author"}, {"merge"}), "PR_AUTHOR_MERGE"),
            (({"code_write"}, {"merge"}), "PR_AUTHOR_MERGE"),
            (({"merge"}, {"deploy"}), "MERGE_DEPLOY"),
            (({"policy_edit"}, {"policy_approve"}), "POLICY_EDIT_APPROVE"),
            (({"hire_request"}, {"hire_approve"}), "HIRE_REQUEST_APPROVE"),
            (({"spend_request"}, {"spend_approve"}), "SPEND_REQUEST_APPROVE"),
            (({"browser_authentication"}, {"external_post"}), "BROWSER_AUTH_EXTERNAL_POST"),
        ],
    )
    def test_each_combination_fires_when_both_sides_are_held(self, tags, code):
        # No capability carries pr_author, merge, deploy, *_approve or policy_* yet, so the rule
        # table is exercised with synthetic tags. The tag test below pins the carried ones.
        mapping = {"x.one": sorted(tags[0]), "x.two": sorted(tags[1])}
        decisions = [
            {"capability_id": c, "decision": "allow", "state": "allowed"}
            for c in ("x.one", "x.two")
        ]
        assert code in {f["code"] for f in risk.combination_findings(decisions, mapping)}
        decisions[1]["decision"] = "deny"
        assert code not in {f["code"] for f in risk.combination_findings(decisions, mapping)}

    def test_secret_network_terminal_needs_all_three(self):
        def dec(cap, state="allowed", decision="allow"):
            return {"capability_id": cap, "decision": decision, "state": state}

        def fired(decisions) -> bool:
            return "SECRET_NETWORK_TERMINAL" in {
                f["code"] for f in risk.combination_findings(decisions)
            }

        secret, net = dec("data.secrets"), dec("tool.http-request")
        shell = dec("computer.terminal", "unsupported", "none")
        assert fired([secret, net, shell])
        assert not fired([net, shell])
        assert not fired([secret, shell, dec("tool.http-request", decision="deny")])

    async def test_uncontrolled_browser_with_default_posting_is_flagged(self, api, t):  # noqa: F811
        body = (await sim(api, t)).json()
        assert "BROWSER_AUTH_EXTERNAL_POST" in codes(body)
        assert "SECRET_NETWORK_TERMINAL" not in codes(body)
        deny_post = {"name": "no post", "effect": "deny",
                     "conditions": {"tool_name": ["http-request", "*-send", "*-notify"]}}
        denied = (await sim(api, t, proposed_rules=[deny_post])).json()
        finding = next(f for f in denied["findings"] if f["code"] == "BROWSER_AUTH_EXTERNAL_POST")
        # Policy now blocks every tool; the autonomy gate still lets a level-1 agent post.
        assert finding["capabilities"] == ["computer.browser", "exec.send_external_message"]

    def test_tags_are_server_owned_real_and_only_where_they_apply(self):
        caps = catalog.catalog_by_id()
        tagged = {cid: set(c["tags"]) for cid, c in caps.items() if c["tags"]}
        assert tagged["computer.terminal"] == {"terminal"}
        assert tagged["computer.browser"] == {"browser_authentication"}
        assert tagged["data.secrets"] == {"secret_reference"}
        assert tagged["tool.http-request"] == {"arbitrary_network", "external_post"}
        assert "arbitrary_network" not in tagged["tool.msg-slack-send"]
        used = set().union(*tagged.values())
        vocabulary = {
            "secret_reference", "arbitrary_network", "terminal", "code_write", "pr_author",
            "merge", "deploy", "hire_request", "hire_approve", "spend_request", "spend_approve",
            "policy_edit", "policy_approve", "external_post", "browser_authentication",
            "fs_write_outside",
        }
        assert used <= vocabulary
        # No capability exists for these, so none may carry them (no tag just to pass a test).
        inert = {"pr_author", "merge", "deploy", "hire_approve", "spend_approve",
                 "policy_edit", "policy_approve"}
        assert not inert & used

    async def test_approval_and_duration_rules(self, t):  # noqa: F811
        def dec(cap, code="POLICY_ALLOW", required=False):
            return {"capability_id": cap, "decision": "allow", "state": "allowed", "code": code,
                    "approval": {"required": required}}

        open_hire = [dec("org.ceo_request_hire"), dec("org.ceo_list_managers"),
                     dec("tool.http-request", "DEFAULT_ALLOW")]
        [found] = risk.approval_findings(open_hire)
        assert found["code"] == "HIGH_RISK_NO_APPROVAL"
        assert found["capabilities"] == ["org.ceo_request_hire"]
        assert risk.approval_findings([dec("org.ceo_request_hire", required=True)]) == []

        now = datetime.now(UTC).replace(tzinfo=None)
        long = _grant(t, risk_level="write", starts_at=now, expires_at=now + timedelta(hours=8))
        short = _grant(t, risk_level="write", starts_at=now, expires_at=now + timedelta(hours=1))
        found = risk.grant_findings([long, short], now + timedelta(minutes=1))
        assert [f["grant_id"] for f in found] == [str(long.id)]
        safe = _grant(t, tool_name="ceo_list_managers", risk_level="read", starts_at=now,
                      expires_at=now + timedelta(hours=8))
        assert risk.grant_findings([safe], now) == []


class TestAttackPathsThroughTheApi:
    async def _bind_fake_secret(self, factory, t):  # noqa: F811
        async with factory() as db:
            secret = Secret(company_id=t["acme"], name="fake-internal", encrypted_value="x")
            db.add(secret)
            await db.flush()
            db.add(SecretBinding(secret_id=secret.id, agent_id=t["a"]))
            await db.commit()

    async def test_secret_network_terminal_appears_and_clears(self, api, factory, t):  # noqa: F811
        assert "SECRET_NETWORK_TERMINAL" not in codes((await sim(api, t)).json())
        await self._bind_fake_secret(factory, t)
        body = (await sim(api, t)).json()
        finding = next(f for f in body["findings"] if f["code"] == "SECRET_NETWORK_TERMINAL")
        assert {"data.secrets", "computer.terminal", "tool.http-request"} <= set(
            finding["capabilities"]
        )
        # Remove one side: the agent loses its secret binding.
        async with factory() as db:
            row = (await db.execute(select(SecretBinding))).scalars().one()
            row.revoked = True
            db.add(row)
            await db.commit()
        assert "SECRET_NETWORK_TERMINAL" not in codes((await sim(api, t)).json())

    async def test_denying_the_network_side_clears_it_too(self, api, factory, t):  # noqa: F811
        await self._bind_fake_secret(factory, t)
        assert "SECRET_NETWORK_TERMINAL" in codes((await sim(api, t)).json())
        no_net = {"name": "no network", "effect": "deny",
                  "conditions": {"tool_name": ["http-request", "*-notify"]}}
        body = (await sim(api, t, proposed_rules=[no_net])).json()
        assert "SECRET_NETWORK_TERMINAL" not in codes(body)
