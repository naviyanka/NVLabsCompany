"""Governance Studio policy drafts, versions, publish and rollback."""

from __future__ import annotations

from typing import Any

from sqlmodel import select

from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernancePolicyVersion
from nexus.models.tool import ToolPolicy
from nexus.services.governance_studio import policies
from nexus.tools.access import check_tool_access
from tests.test_governance_studio import api  # noqa: F401 -- fixture
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper

DENY_WRITES = {"name": "deny writes", "effect": "deny", "conditions": {"risk_level": ["write"]}}
ALLOW_READ = {"name": "allow reads", "effect": "allow", "conditions": {"risk_level": ["read"]}}
ALLOW_ALL = {"name": "allow all", "effect": "allow", "conditions": {}}


def body(*rules: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {"rules": list(rules), "reason": "tighten writes", **over}


async def draft(api, *rules, who="admin", **over) -> dict[str, Any]:  # noqa: F811
    r = await api("POST", "/drafts", body(*rules, **over), who=who)
    assert r.status_code == 201, r.text
    return r.json()


async def publish(api, d, who="admin"):  # noqa: F811
    return await api("POST", f"/drafts/{d['id']}/publish", {}, who=who)


async def writes_allowed(factory, t) -> bool:  # noqa: F811
    async with factory() as db:
        return (
            await check_tool_access(
                db, ctx(t), tool_name="manager_delegate_task", default_risk="write",
                enforcement="audit",
            )
        ).allowed


class TestDrafts:
    async def test_a_draft_shows_its_diff_and_findings_and_changes_nothing(self, api, factory, t):  # noqa: F811
        d = await draft(api, DENY_WRITES, ALLOW_ALL)
        assert d["status"] == "draft" and d["base_version"] == 0 and not d["stale"]
        assert [r["name"] for r in d["diff"]["added"]] == ["deny writes", "allow all"] or {
            r["name"] for r in d["diff"]["added"]} == {"deny writes", "allow all"}
        assert d["loosens"] and {f["code"] for f in d["findings"]} >= {"WILDCARD_HIGH_RISK"}
        assert (await api("GET", "/policy")).json() == {"version": 0, "rules": []}
        assert await writes_allowed(factory, t)

    async def test_validation_and_access(self, api, t):  # noqa: F811
        dup = await api("POST", "/drafts", body(DENY_WRITES, DENY_WRITES))
        assert dup.status_code == 422
        unknown = {"name": "x", "effect": "deny", "conditions": {"shell": "x"}}
        assert (await api("POST", "/drafts", body(unknown))).status_code == 422
        short = await api("POST", "/drafts", {"rules": [], "reason": "no"})
        assert short.status_code == 422
        for who in ("viewer", "run", "key"):
            assert (await api("POST", "/drafts", body(DENY_WRITES), who=who)).status_code == 403
        d = await draft(api, DENY_WRITES)
        for who in ("run", "key"):
            assert (await api("GET", f"/drafts/{d['id']}", who=who)).status_code == 403
        assert (await api("GET", f"/drafts/{d['id']}", who="viewer")).status_code == 200
        assert (await api("GET", f"/drafts/{d['id']}", who="outsider")).status_code == 404
        assert len((await api("GET", "/drafts", who="outsider")).json()["items"]) == 0

    async def test_only_the_author_edits_and_anyone_admin_discards(self, api, t):  # noqa: F811
        d = await draft(api, DENY_WRITES)
        edit = body(DENY_WRITES, ALLOW_READ)
        assert (await api("PUT", f"/drafts/{d['id']}", edit)).json()["diff"]["added"].__len__() == 2
        other = await api("PUT", f"/drafts/{d['id']}", edit, who="second_admin")
        assert (other.status_code, other.json()["detail"]["code"]) == (403, "NOT_AUTHOR")
        gone = await api("POST", f"/drafts/{d['id']}/discard", {}, who="second_admin")
        assert gone.json()["status"] == "discarded"
        again = await api("POST", f"/drafts/{d['id']}/discard", {})
        assert again.json()["detail"]["code"] == "DRAFT_NOT_OPEN"
        assert (await publish(api, d)).json()["detail"]["code"] == "DRAFT_NOT_OPEN"


class TestPublish:
    async def test_a_tightening_change_publishes_and_the_runtime_follows(self, api, factory, t):  # noqa: F811
        d = await draft(api, DENY_WRITES)
        assert not d["loosens"]
        done = await publish(api, d)
        assert done.status_code == 200 and done.json()["status"] == "published"
        assert done.json()["published_version"] == 2
        assert not await writes_allowed(factory, t)
        live = (await api("GET", "/policy")).json()
        assert live["version"] == 2 and [r["name"] for r in live["rules"]] == ["deny writes"]
        versions = (await api("GET", "/versions")).json()["items"]
        assert [(v["version"], v["status"]) for v in versions] == [(2, "active"), (1, "superseded")]
        one = (await api("GET", "/versions/1")).json()
        assert one["rules"] == [] and one["reason"].startswith("Rules in force")
        two = (await api("GET", "/versions/2")).json()
        assert [r["name"] for r in two["diff_from_previous"]["added"]] == ["deny writes"]
        assert (await api("GET", "/versions/9")).status_code == 404

    async def test_a_loosening_change_needs_someone_other_than_the_author(self, api, factory, t):  # noqa: F811
        d = await draft(api, ALLOW_READ)
        assert d["loosens"]
        own = await publish(api, d)
        assert (own.status_code, own.json()["detail"]["code"]) == (403, "REVIEWER_REQUIRED")
        assert (await publish(api, d, who="viewer")).status_code == 403
        ok = await publish(api, d, who="second_admin")
        assert ok.status_code == 200 and ok.json()["published_version"] == 2

    async def test_a_named_reviewer_list_is_binding(self, api, t):  # noqa: F811
        d = await draft(api, ALLOW_READ, reviewers=["someone@example.test"])
        wrong = await publish(api, d, who="second_admin")
        assert (wrong.status_code, wrong.json()["detail"]["code"]) == (403, "NOT_A_REVIEWER")
        self_listed = await draft(api, ALLOW_READ, reviewers=["p@example.test"])
        assert "SELF_REVIEW" in {f["code"] for f in self_listed["findings"]}

    async def test_a_second_draft_from_the_same_base_is_stale(self, api, t):  # noqa: F811
        first, second = await draft(api, DENY_WRITES), await draft(api, ALLOW_READ)
        assert (await publish(api, first)).status_code == 200
        late = await publish(api, second, who="second_admin")
        assert (late.status_code, late.json()["detail"]["code"]) == (409, "STALE_BASE")
        assert (await api("GET", f"/drafts/{second['id']}")).json()["stale"] is True
        assert (await api("GET", "/policy")).json()["version"] == 2

    async def test_the_same_draft_cannot_publish_twice(self, api, t):  # noqa: F811
        d = await draft(api, DENY_WRITES)
        assert (await publish(api, d)).status_code == 200
        again = await publish(api, d)
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "DRAFT_NOT_OPEN")

    async def test_losing_the_version_race_rolls_everything_back(
        self, api, factory, t, monkeypatch  # noqa: F811
    ):
        d = await draft(api, DENY_WRITES)
        async with factory() as db:
            db.add(GovernancePolicyVersion(
                company_id=t["acme"], version_number=1, published_by="x"))
            await db.commit()

        async def behind(*_a):
            return 0

        real = policies.current_version
        monkeypatch.setattr(policies, "current_version", behind)
        r = await publish(api, d)
        assert (r.status_code, r.json()["detail"]["code"]) == (409, "VERSION_CONFLICT")
        async with factory() as db:
            assert not (await db.execute(select(ToolPolicy))).scalars().all()
            assert len((await db.execute(select(GovernancePolicyVersion))).scalars().all()) == 1
        monkeypatch.setattr(policies, "current_version", real)
        assert (await api("GET", f"/drafts/{d['id']}")).json()["status"] == "draft"

    async def test_publish_is_audited_without_rule_contents(self, api, factory, t):  # noqa: F811
        await publish(api, await draft(api, ALLOW_ALL, reviewers=[]), who="second_admin")
        async with factory() as db:
            rows = (
                await db.execute(
                    select(AuditLog).where(AuditLog.action == "governance.policy.published")
                )
            ).scalars().all()
        assert len(rows) == 1
        detail = rows[0].details
        assert detail["loosens"] is True and "WILDCARD_HIGH_RISK" in detail["findings"]
        assert "conditions" not in str(detail)


class TestRollback:
    async def _two_versions(self, api, *rules):  # noqa: F811
        """Version 1 is the empty baseline; version 2 holds ``rules``."""
        d = await draft(api, *rules)
        assert (await publish(api, d, who="second_admin")).status_code == 200

    async def test_rolling_back_a_loosening_publish_applies_at_once(self, api, factory, t):  # noqa: F811
        await self._two_versions(api, ALLOW_READ)
        r = await api("POST", "/versions/1/rollback",
                      {"reason": "undo the allow", "expected_version": 2})
        assert r.status_code == 200 and r.json() == {"applied": True, "version": 3}
        live = (await api("GET", "/policy")).json()
        assert live == {"version": 3, "rules": []}
        v3 = (await api("GET", "/versions/3")).json()
        assert (v3["rollback_of"], v3["status"]) == (1, "active")
        assert (await api("GET", "/versions/2")).json()["status"] == "superseded"

    async def test_a_rollback_that_would_loosen_goes_through_review(self, api, factory, t):  # noqa: F811
        await self._two_versions(api, DENY_WRITES)
        assert not await writes_allowed(factory, t)
        r = await api("POST", "/versions/1/rollback",
                      {"reason": "remove the deny", "expected_version": 2})
        out = r.json()
        assert out["applied"] is False and out["draft"]["loosens"]
        assert not await writes_allowed(factory, t)
        own = await publish(api, out["draft"])
        assert own.json()["detail"]["code"] == "REVIEWER_REQUIRED"
        assert (await publish(api, out["draft"], who="second_admin")).status_code == 200
        assert await writes_allowed(factory, t)

    async def test_rollback_checks_the_version_and_the_caller(self, api, t):  # noqa: F811
        await self._two_versions(api, ALLOW_READ)
        undo = {"reason": "undo it", "expected_version": 2}
        stale = await api("POST", "/versions/1/rollback", {**undo, "expected_version": 1})
        assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "STALE_BASE")
        missing = await api("POST", "/versions/7/rollback", undo)
        assert missing.status_code == 404
        for who in ("viewer", "run", "key"):
            r = await api("POST", "/versions/1/rollback", undo, who=who)
            assert r.status_code == 403, who


class TestStudioReads:
    async def test_affects_names_the_agents_and_capabilities_a_change_touches(self, api, t):  # noqa: F811
        scoped = {"name": "a only", "effect": "deny",
                  "conditions": {"agent_id": [str(t["a"])], "tool_name": ["http-request", "ai-*"]}}
        d = await draft(api, scoped)
        assert d["affects"]["agent_ids"] == [str(t["a"])] and not d["affects"]["all_agents"]
        assert "tool.http-request" in d["affects"]["capability_ids"]
        assert "tool.ai-chat" in d["affects"]["capability_ids"]
        assert "tool.msg-slack-send" not in d["affects"]["capability_ids"]
        wide = await draft(api, DENY_WRITES)
        assert wide["affects"]["all_agents"]

    async def test_impact_is_the_real_decision_and_writes_nothing(self, api, factory, t):  # noqa: F811
        d = await draft(api, DENY_WRITES)
        r = await api("GET", f"/drafts/{d['id']}/impact?agent_id={t['a']}")
        changes = {c["capability_id"]: c for c in r.json()["capability_diff"]["changes"]}
        assert changes["tool.http-request"]["before"] == "allow"
        assert changes["tool.http-request"]["after"] == "deny"
        assert await writes_allowed(factory, t), "a preview changes nothing"
        assert (await api("GET", f"/drafts/{d['id']}/impact?agent_id={t['b']}")).status_code == 200
        assert (await api("GET", f"/drafts/{d['id']}/impact?agent_id={t['b']}",
                          who="outsider")).status_code == 404

    async def test_rollback_preview_shows_the_exact_change(self, api, t):  # noqa: F811
        await publish(api, await draft(api, ALLOW_READ), who="second_admin")
        await publish(api, await draft(api, ALLOW_READ, DENY_WRITES))
        same = (await api("GET", "/versions/3/rollback-preview")).json()
        assert (same["target_version"], same["current_version"]) == (3, 3)
        assert same["diff"] == {"added": [], "removed": [], "changed": []}
        back = (await api("GET", "/versions/2/rollback-preview")).json()
        assert [r["name"] for r in back["diff"]["removed"]] == ["deny writes"]
        assert back["loosens"] and not back["applies_at_once"]
        assert (await api("GET", "/versions/99/rollback-preview")).status_code == 404

    async def test_publish_and_edit_carry_an_optimistic_check(self, api, t):  # noqa: F811
        d = await draft(api, DENY_WRITES)
        stale = await api("POST", f"/drafts/{d['id']}/publish", {"expected_version": 4})
        assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "STALE_BASE")
        edit = {**body(DENY_WRITES, reason="second thought"), "expected_updated_at": "1999-01-01"}
        lost = await api("PUT", f"/drafts/{d['id']}", edit)
        assert (lost.status_code, lost.json()["detail"]["code"]) == (409, "STALE_EDIT")
        edit["expected_updated_at"] = d["updated_at"]
        assert (await api("PUT", f"/drafts/{d['id']}", edit)).status_code == 200
        ok = await api("POST", f"/drafts/{d['id']}/publish", {"expected_version": 0})
        assert ok.status_code == 200
