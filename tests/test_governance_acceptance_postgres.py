"""Governance Studio acceptance: 30 scenarios on a real, migrated PostgreSQL database.

Routes run as the application role (row-level security applies). Direct reads and seeding use the
migration role. Only fake and internal tools are used: nothing is sent outside the database.
Set ``GOVERNANCE_EVIDENCE_DIR`` to save sanitized evidence (scenario, result and counts, never
ids, secrets, prompts, memory or tokens).
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import select

from nexus.config import settings
from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernanceGrantUse, GovernanceTempAccess
from nexus.models.secret import Secret, SecretBinding
from nexus.models.tool import ToolPolicy
from nexus.tools import governance_overlay
from tests.test_governance_grant_runtime import _call, _close, _row, _three_ways
from tests.test_governance_grants import (  # noqa: F401 -- fixtures and helpers
    HIRE,
    READ,
    _active_allow,
    _create,
    _decide,
    _grant,
    _in,
)
from tests.test_governance_policies import ALLOW_READ, DENY_WRITES, draft, publish
from tests.test_governance_runtime import LOCK, UNLOCK, WHY, _allowed, _status, _work
from tests.test_governance_simulator import codes, sim
from tests.test_governance_studio import _policy, api  # noqa: F401 -- fixtures, helpers
from tests.test_postgres_integration import (  # noqa: F401 -- module fixtures
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
)
from tests.test_tool_access import ctx, t  # noqa: F401 -- fixtures and helper

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

DENY_READS = {"name": "deny reads", "effect": "deny", "conditions": {"risk_level": ["read"]}}
HIRE_CAP = "org.ceo_request_hire"
TERMINAL = "computer.terminal"
_RESULTS: list[dict[str, Any]] = []


@pytest.fixture
async def factory(migrated_postgres_url, app_user_postgres_url, monkeypatch):  # noqa: F811
    """Migration-role sessions seed and read; routes and grant spends run as the app role."""
    admin = create_async_engine(migrated_postgres_url)
    app = create_async_engine(app_user_postgres_url, pool_size=10)
    import nexus.database as database

    monkeypatch.setattr(
        database, "async_session_factory", async_sessionmaker(app, expire_on_commit=False)
    )
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    yield async_sessionmaker(admin, class_=AsyncSession, expire_on_commit=False)
    await admin.dispose()
    await app.dispose()


@pytest.fixture(scope="module", autouse=True)
def evidence():
    yield
    target = os.environ.get("GOVERNANCE_EVIDENCE_DIR")
    if not target:
        return
    out = Path(target)
    out.mkdir(parents=True, exist_ok=True)
    rows = sorted(_RESULTS, key=lambda r: r["scenario"])
    summary = {
        "database": "disposable PostgreSQL, all migrations applied, routes as a non-superuser",
        "tools": "fake and internal only; no external call was made",
        "passed": sum(r["result"] == "pass" for r in rows),
        "total": len(rows),
        "scenarios": rows,
    }
    (out / "acceptance.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


class Obs:
    def __init__(self, number: int, title: str) -> None:
        self.row = {"scenario": number, "title": title, "result": "fail", "observed": {}}
        _RESULTS.append(self.row)

    def note(self, **facts: Any) -> None:
        self.row["observed"].update(facts)

    def done(self) -> None:
        self.row["result"] = "pass"


@pytest.fixture
def obs(request):
    name = request.node.name  # test_s07_...
    number = int(name.split("_")[1][1:])
    return Obs(number, (request.node.function.__doc__ or name).strip())


async def _count(factory, model, company) -> int:  # noqa: F811
    async with factory() as db:
        count = select(sa.func.count()).select_from(model).where(model.company_id == company)
        return (await db.execute(count)).scalar_one()


async def _fake_secret(factory, t, value="not-a-real-secret") -> uuid.UUID:  # noqa: F811
    async with factory() as db:
        secret = Secret(company_id=t["acme"], name="fake-internal", encrypted_value=value)
        db.add(secret)
        await db.flush()
        binding = SecretBinding(secret_id=secret.id, agent_id=t["a"])
        db.add(binding)
        await db.commit()
        return binding.id


async def _policy_rules(api) -> tuple[int, list[dict[str, Any]]]:  # noqa: F811
    body = (await api("GET", "/policy")).json()
    return body["version"], body["rules"]


async def _version_flow(api):  # noqa: F811
    """v_a denies writes and reads, v_b (a loosening) denies writes only. Returns (a, b)."""
    a = await publish(api, await draft(api, DENY_WRITES, DENY_READS))
    assert a.status_code == 200, a.text
    b = await publish(api, await draft(api, DENY_WRITES), who="second_admin")
    assert b.status_code == 200, b.text
    return a.json()["published_version"], b.json()["published_version"]


async def test_s01_viewer_reads_but_cannot_edit(api, t, obs):  # noqa: F811
    """A viewer can inspect permitted read views but cannot edit."""
    for path in ("/catalog", "/agents", f"/agents/{t['a']}/effective-access", "/grants",
                 "/drafts", "/versions", "/audit"):
        assert (await api("GET", path, who="viewer")).status_code == 200, path
    refused = {}
    for name, path, body in (
        ("grant", "/grants", _grant(t)),
        ("draft", "/drafts", {"rules": [DENY_WRITES], "reason": "viewer try"}),
        ("lockdown", "/lockdown", LOCK),
        ("simulate_publish", "/drafts/" + str(uuid.uuid4()) + "/publish", {}),
    ):
        refused[name] = (await api("POST", path, body, who="viewer")).status_code
    assert set(refused.values()) == {403}
    obs.note(reads="200", writes=refused)
    obs.done()


async def test_s02_admin_creates_a_temporary_read_grant(api, factory, t, obs):  # noqa: F811
    """An admin creates a temporary read grant, and it really lets a denied read through."""
    await _close(factory, t)
    assert not (await _decide(factory, t, tool=READ)).allowed
    g = await _create(api, t, tool=READ)
    assert g["status"] == "active"
    assert (await _decide(factory, t, tool=READ)).allowed
    obs.note(before="deny", grant_status=g["status"], after="allow")
    obs.done()


async def test_s03_admin_creates_a_one_use_write_grant(api, factory, t, obs):  # noqa: F811
    """An admin creates a one-use write grant; it waits for a second person."""
    g = await _create(api, t, max_uses=1)
    assert g["status"] == "pending_approval"
    assert not (await _decide(factory, t)).allowed
    ok = await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
    assert ok.json()["status"] == "active"
    assert (await _decide(factory, t)).allowed
    obs.note(created="pending_approval", after_approval="active", uses=1)
    obs.done()


async def test_s04_one_use_grant_works_exactly_once(api, factory, t, obs):  # noqa: F811
    """A one-use grant works exactly once through the real guarded call."""
    g = await _active_allow(api, t, max_uses=1)
    first, ran1 = _call(t, HIRE)
    second, ran2 = _call(t, HIRE)
    a, b = await first(), await second()
    row = await _row(factory, g["id"])
    assert (a["status"], b["status"] != "success") == ("success", True)
    assert (len(ran1), len(ran2)) == (1, 0)
    assert (row.used_count, row.status) == (1, "used_up")
    obs.note(first=a["status"], second="blocked", tool_runs=1, status=row.status)
    obs.done()


async def test_s05_expiry_removes_access_without_a_scheduler(api, factory, t, obs):  # noqa: F811
    """Expiry removes access with no scheduler running."""
    g = await _active_allow(api, t)
    assert (await _decide(factory, t)).allowed
    async with factory() as db:
        row = await db.get(GovernanceTempAccess, uuid.UUID(g["id"]))
        row.expires_at = governance_overlay.now() - timedelta(minutes=1)
        db.add(row)
        await db.commit()
    assert not (await _decide(factory, t)).allowed
    listed = (await api("GET", "/grants?status=expired")).json()["items"]
    assert [i["id"] for i in listed] == [g["id"]]
    obs.note(before="allow", after_expiry="deny", listed_as="expired")
    obs.done()


async def test_s06_explicit_deny_defeats_a_temporary_allow(api, factory, t, obs):  # noqa: F811
    """An explicit deny rule defeats a temporary allow."""
    await _policy(factory, t["acme"], name="freeze hiring", effect="deny",
                  conditions={"tool_name": [HIRE]})
    await _active_allow(api, t)
    decision = await _decide(factory, t)
    assert not decision.allowed and decision.temp_grant_id is None
    obs.note(grant="active", decision="deny", grant_used=False)
    obs.done()


async def test_s07_unsupported_backend_remains_unsupported(api, factory, t, obs):  # noqa: F811
    """An unsupported backend stays unsupported and cannot be granted."""
    caps = {c["id"]: c for c in (await api("GET", "/catalog")).json()["capabilities"]}
    assert caps[TERMINAL]["support"] == "unsupported" and not caps[TERMINAL]["toggleable"]
    eff = (await api("GET", f"/agents/{t['a']}/effective-access")).json()["capabilities"]
    state = next(c for c in eff if c["id"] == TERMINAL)
    assert state["state"] == "unsupported"
    refused = await api("POST", "/grants", _grant(t, tool=TERMINAL))
    assert (refused.status_code, refused.json()["detail"]["code"]) == (422, "UNKNOWN_TOOL")
    obs.note(support="unsupported", state=state["state"], grant="422 UNKNOWN_TOOL")
    obs.done()


async def test_s08_high_risk_grant_requires_approval(api, factory, t, obs):  # noqa: F811
    """A high-risk grant needs approval and grants nothing until then."""
    g = await _create(api, t)
    assert g["status"] == "pending_approval" and g["approval_id"]
    assert not (await _decide(factory, t)).allowed
    obs.note(status=g["status"], approval_requested=True, access="deny")
    obs.done()


async def test_s09_requester_cannot_self_approve(api, factory, t, obs):  # noqa: F811
    """A requester cannot approve their own grant."""
    g = await _create(api, t)
    own = await api("POST", f"/grants/{g['id']}/approve", {})
    assert (own.status_code, own.json()["detail"]["code"]) == (403, "SELF_APPROVAL")
    assert not (await _decide(factory, t)).allowed
    obs.note(self_approval="403 SELF_APPROVAL", access="deny")
    obs.done()


async def test_s10_simulator_explains_without_invoking_a_tool(api, factory, t, obs):  # noqa: F811
    """The simulator explains allow and deny and invokes nothing."""
    await _active_allow(api, t, max_uses=1)
    audits = await _count(factory, AuditLog, t["acme"])
    uses = (await _row_any(factory, t)).used_count
    body = (await sim(api, t, cap=HIRE_CAP)).json()
    assert body["current"]["decision"] == "allow" and body["current"]["steps"]
    assert any("Nothing was called" in n for n in body["notes"])
    denied = (await sim(api, t, cap="org.ceo_record_decision")).json()["current"]
    assert denied["decision"] == "deny" and denied["explanation"]
    assert await _count(factory, AuditLog, t["acme"]) == audits
    assert (await _row_any(factory, t)).used_count == uses == 0
    obs.note(allow_explained=True, deny_explained=True, audit_rows_added=0, uses_spent=0)
    obs.done()


async def _row_any(factory, t) -> GovernanceTempAccess:  # noqa: F811
    async with factory() as db:
        rows = select(GovernanceTempAccess).where(GovernanceTempAccess.company_id == t["acme"])
        return (await db.execute(rows)).scalars().first()


async def test_s11_publish_creates_a_new_version(api, t, obs):  # noqa: F811
    """Publishing creates a new immutable version."""
    before, _ = await _policy_rules(api)
    r = await publish(api, await draft(api, DENY_WRITES))
    assert r.status_code == 200, r.text
    after, rules = await _policy_rules(api)
    versions = (await api("GET", "/versions")).json()["items"]
    assert after > before and [x["name"] for x in rules] == ["deny writes"]
    assert [v["status"] for v in versions].count("active") == 1
    obs.note(version_before=before, version_after=after, active_versions=1)
    obs.done()


async def test_s12_stale_concurrent_publish_fails(api, t, obs):  # noqa: F811
    """Two publishes from one base leave one winner and one 409."""
    d1 = await draft(api, DENY_WRITES)
    d2 = await draft(api, DENY_READS)
    r1, r2 = await asyncio.gather(publish(api, d1), publish(api, d2, who="second_admin"))
    statuses = sorted([r1.status_code, r2.status_code])
    assert statuses == [200, 409]
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["detail"]["code"] in {"STALE_BASE", "VERSION_CONFLICT"}
    obs.note(statuses=statuses, loser_code=loser.json()["detail"]["code"])
    obs.done()


async def test_s13_rollback_creates_a_new_version(api, t, obs):  # noqa: F811
    """Rollback creates a new version and keeps every older one."""
    a, b = await _version_flow(api)
    n = (await api("GET", "/versions")).json()["items"]
    r = await api("POST", f"/versions/{a}/rollback",
                  {"reason": "restore the stricter set", "expected_version": b})
    assert r.status_code == 200 and r.json()["applied"], r.text
    after = (await api("GET", "/versions")).json()["items"]
    newest = max(after, key=lambda v: v["version"])
    assert len(after) == len(n) + 1 and newest["rollback_of"] == a
    assert newest["status"] == "active"
    obs.note(versions_before=len(n), versions_after=len(after), history_kept=True)
    obs.done()


async def test_s14_cancellation_affects_only_the_selected_execution(api, factory, t, obs):  # noqa: F811
    """Runtime cancellation touches only the selected attempt."""
    mine = await _work(factory, t)
    other = await _work(factory, t, agent="b", session="s2")
    r = await api("POST", f"/runtime/attempts/{mine['attempt']}/cancel", WHY)
    assert r.json()["status"] == "cancelled"
    from nexus.models.chat_turn import ChatTurn
    from nexus.models.task_attempt import TaskAttempt

    states = (
        await _status(factory, TaskAttempt, mine["attempt"]),
        await _status(factory, ChatTurn, mine["turn"]),
        await _status(factory, TaskAttempt, other["attempt"]),
        await _status(factory, ChatTurn, other["turn"]),
    )
    assert states == ("cancelled", "queued", "queued", "queued")
    obs.note(selected_attempt="cancelled", same_agent_turn="queued", other_agent="queued")
    obs.done()


async def test_s15_lockdown_blocks_agent_writes(api, factory, t, obs):  # noqa: F811
    """Lockdown blocks writes and leaves reads."""
    assert await _allowed(factory, t) and await _allowed(factory, t, risk="read")
    assert (await api("POST", "/lockdown", {"reason": "drill", "confirm": "no"})).status_code == 422
    assert (await api("POST", "/lockdown", LOCK)).status_code == 201
    assert not await _allowed(factory, t)
    assert await _allowed(factory, t, risk="read")
    obs.note(confirm_phrase_required=True, write="deny", read="allow")
    obs.done()


async def test_s16_release_restores_the_prior_policy_state(api, factory, t, obs):  # noqa: F811
    """Releasing the lockdown restores exactly the earlier policy state."""
    await publish(api, await draft(api, DENY_READS))
    before = await _policy_rules(api)
    await api("POST", "/lockdown", LOCK)
    assert not await _allowed(factory, t)
    assert (await api("POST", "/lockdown/release", UNLOCK)).status_code == 200
    assert await _allowed(factory, t)
    assert not await _allowed(factory, t, risk="read")  # the published deny still holds
    assert await _policy_rules(api) == before
    obs.note(write_after_release="allow", published_deny_still_holds=True, policy_unchanged=True)
    obs.done()


async def test_s17_another_tenant_gets_404(api, t, obs):  # noqa: F811
    """Another tenant's agent and grant are 404."""
    g = await _create(api, t)
    agent = await api("GET", f"/agents/{t['a']}/effective-access", who="outsider")
    grant = await api("POST", f"/grants/{g['id']}/approve", {}, who="outsider")
    assert (agent.status_code, grant.status_code) == (404, 404)
    obs.note(agent=404, grant=404)
    obs.done()


async def test_s18_audit_has_identity_and_no_secrets(api, factory, t, obs):  # noqa: F811
    """The audit trail names who did what and holds no secret value."""
    planted = "zz-planted-secret-value"
    await _fake_secret(factory, t, planted)
    g = await _create(api, t, reason="incident 42")
    await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
    await api("POST", "/lockdown", LOCK)
    await api("POST", f"/agents/{t['a']}/isolate", WHY)
    items = (await api("GET", "/audit", who="viewer")).json()["items"]
    actions = {i["action"] for i in items}
    assert {"governance.grant.created", "governance.grant.approved",
            "governance.lockdown.started", "governance.isolation.started"} <= actions
    assert all(i["actor"] and i["resource_type"] and i["resource_id"] and i["at"] for i in items)
    blob = json.dumps(items).lower()
    assert planted not in blob and "bearer" not in blob and "password" not in blob
    assert {i["actor"] for i in items} >= {"p@example.test", "q@example.test"}
    obs.note(actions=sorted(actions), every_row_has_actor_resource_time=True, secret_present=False)
    obs.done()


async def test_s19_simulator_and_runtime_agree(api, factory, t, obs):  # noqa: F811
    """The simulator, the matrix and the real engine give the same decision."""
    await _close(factory, t)
    seen = {}
    seen["safe_default_denied"] = await _three_ways(api, factory, t, READ)
    await _create(api, t, tool=READ)
    seen["safe_with_grant"] = await _three_ways(api, factory, t, READ)
    seen["high_risk_no_grant"] = await _three_ways(api, factory, t, HIRE)
    await _active_allow(api, t)
    seen["high_risk_approved"] = await _three_ways(api, factory, t, HIRE)
    assert all(len(set(v)) == 1 for v in seen.values()), seen
    assert [v[0] for v in seen.values()] == [False, True, False, True]
    obs.note(cases={k: ("allow" if v[0] else "deny") for k, v in seen.items()}, agree=True)
    obs.done()


async def test_s20_simulator_consumes_no_one_use_grant(api, factory, t, obs):  # noqa: F811
    """Simulating and reading the matrix never spend a one-use grant."""
    g = await _active_allow(api, t, max_uses=1)
    for _ in range(3):
        assert (await sim(api, t, cap=HIRE_CAP)).json()["current"]["decision"] == "allow"
        await api("GET", f"/agents/{t['a']}/effective-access")
    row = await _row(factory, g["id"])
    assert (row.used_count, row.status) == (0, "active")
    assert await _count(factory, GovernanceGrantUse, t["acme"]) == 0
    obs.note(simulations=3, matrix_reads=3, used_count=0)
    obs.done()


async def test_s21_a_real_invocation_consumes_exactly_one_use(api, factory, t, obs):  # noqa: F811
    """One real invocation spends exactly one use."""
    g = await _active_allow(api, t, max_uses=3)
    go, ran = _call(t, HIRE)
    assert (await go())["status"] == "success"
    row = await _row(factory, g["id"])
    assert (row.used_count, row.status, len(ran)) == (1, "active", 1)
    obs.note(invocations=1, used_count=row.used_count, status=row.status)
    obs.done()


async def test_s22_a_draft_is_visible_and_editable(api, t, obs):  # noqa: F811
    """A policy draft is listed with its fields and its author can edit it."""
    d = await draft(api, DENY_WRITES, reason="freeze writes for the audit")
    listed = (await api("GET", "/drafts")).json()["items"]
    row = next(i for i in listed if i["id"] == d["id"])
    assert {"status", "base_version", "reason", "created_by", "created_at", "stale"} <= set(row)
    edited = await api("PUT", f"/drafts/{d['id']}", {
        "rules": [DENY_WRITES, ALLOW_READ], "reason": "freeze writes for the audit",
        "expected_updated_at": d["updated_at"],
    })
    assert edited.status_code == 200 and len(edited.json()["rules"]) == 2
    obs.note(listed_fields=sorted(row), edit="200", rules_after_edit=2,
             surface="API; the dashboard screens are covered by the Governance Studio vitest suite")
    obs.done()


async def test_s23_publish_activates_the_new_version(api, factory, t, obs):  # noqa: F811
    """Publish turns a draft into the active rules the engine enforces."""
    assert await _allowed(factory, t)
    r = await publish(api, await draft(api, DENY_WRITES))
    assert r.status_code == 200 and not await _allowed(factory, t)
    assert await _allowed(factory, t, risk="read")
    obs.note(write_before="allow", write_after="deny", read_after="allow")
    obs.done()


async def test_s24_a_stale_edit_or_publish_returns_a_conflict(api, t, obs):  # noqa: F811
    """A stale edit and a stale publish return a visible 409."""
    d = await draft(api, DENY_WRITES)
    first = await api("PUT", f"/drafts/{d['id']}", {
        "rules": [DENY_WRITES], "reason": "first edit here",
        "expected_updated_at": d["updated_at"]})
    assert first.status_code == 200
    stale = await api("PUT", f"/drafts/{d['id']}", {
        "rules": [DENY_READS], "reason": "second edit", "expected_updated_at": d["updated_at"]})
    assert (stale.status_code, stale.json()["detail"]["code"]) == (409, "STALE_EDIT")
    lost = await api("POST", f"/drafts/{d['id']}/publish", {"expected_version": 99})
    assert lost.status_code == 409
    obs.note(stale_edit="409 STALE_EDIT", stale_publish=f"409 {lost.json()['detail']['code']}")
    obs.done()


async def test_s25_rollback_restores_behavior(api, factory, t, obs):  # noqa: F811
    """Rollback to an earlier version restores its behavior as a new version."""
    a, b = await _version_flow(api)
    assert await _allowed(factory, t, risk="read")  # v_b allows reads
    preview = (await api("GET", f"/versions/{a}/rollback-preview")).json()
    assert preview["diff"]["added"] and preview["applies_at_once"] is True
    r = await api("POST", f"/versions/{a}/rollback",
                  {"reason": "restore the stricter set", "expected_version": b})
    assert r.status_code == 200 and r.json()["applied"], r.text
    assert not await _allowed(factory, t, risk="read") and not await _allowed(factory, t)
    obs.note(read_before="allow", read_after="deny", write_after="deny", new_version=True)
    obs.done()


async def test_s26_an_autonomy_preset_creates_a_draft_only(api, factory, t, obs):  # noqa: F811
    """A preset creates a draft and changes nothing until it is published."""
    version, _ = await _policy_rules(api)
    policies_before = await _count(factory, ToolPolicy, t["acme"])
    r = await api("POST", f"/agents/{t['a']}/autonomy-presets/advisory/draft",
                  {"reason": "try the advisory preset"})
    assert r.status_code == 201, r.text
    assert (await _policy_rules(api))[0] == version
    assert await _count(factory, ToolPolicy, t["acme"]) == policies_before
    assert await _allowed(factory, t)
    for method in ("PUT", "POST"):
        setter = await api(method, f"/agents/{t['a']}/autonomy", {"level": "L3"})
        assert setter.status_code in (404, 405)
    obs.note(draft="created", active_policy="unchanged", write_still="allow",
             direct_setter="absent")
    obs.done()


async def test_s27_attack_path_findings_appear_for_a_real_tagged_combination(api, factory, t, obs):  # noqa: F811
    """A secret, arbitrary network and terminal together raise a finding."""
    assert "SECRET_NETWORK_TERMINAL" not in codes((await sim(api, t)).json())
    await _fake_secret(factory, t)
    finding = next(f for f in (await sim(api, t)).json()["findings"]
                   if f["code"] == "SECRET_NETWORK_TERMINAL")
    assert {"data.secrets", TERMINAL} <= set(finding["capabilities"])
    obs.note(finding="SECRET_NETWORK_TERMINAL", severity=finding["severity"],
             capabilities=finding["capabilities"])
    obs.done()


async def test_s28_removing_one_side_clears_the_finding(api, factory, t, obs):  # noqa: F811
    """Revoking the secret binding clears the finding."""
    binding = await _fake_secret(factory, t)
    assert "SECRET_NETWORK_TERMINAL" in codes((await sim(api, t)).json())
    async with factory() as db:
        row = await db.get(SecretBinding, binding)
        row.revoked = True
        db.add(row)
        await db.commit()
    assert "SECRET_NETWORK_TERMINAL" not in codes((await sim(api, t)).json())
    obs.note(before="finding", after_secret_revoked="cleared")
    obs.done()


async def test_s29_an_unsupported_computer_use_capability_cannot_be_enabled(api, t, obs):  # noqa: F811
    """No grant, rule or preset can turn on an unenforceable capability."""
    allow_all = {"name": "allow all", "effect": "allow", "conditions": {}}
    body = (await sim(api, t, cap=TERMINAL, proposed_rules=[allow_all])).json()
    assert body["current"]["code"] == body["proposed"]["code"] == "NOT_ENFORCEABLE"
    assert body["proposed"]["decision"] != "allow"
    grant = await api("POST", "/grants", _grant(t, tool=TERMINAL))
    assert grant.status_code == 422
    preview = (await api("GET", f"/agents/{t['a']}/autonomy-presets/advisory")).json()
    excluded = {e["capability_id"] for e in preview["capability_diff"]["excluded"]}
    assert TERMINAL in excluded
    obs.note(simulated_with_allow_all="deny NOT_ENFORCEABLE", grant="422", preset="excluded")
    obs.done()


async def test_s30_cross_tenant_ids_are_404(api, t, obs):  # noqa: F811
    """Another tenant's agent, grant, draft and version ids are all 404."""
    g = await _create(api, t)
    d = await draft(api, DENY_WRITES)
    await publish(api, d)
    paths = {
        "agent": ("GET", f"/agents/{t['a']}/effective-access", None),
        "agent_presets": ("GET", f"/agents/{t['a']}/autonomy-presets", None),
        "grant_approve": ("POST", f"/grants/{g['id']}/approve", {}),
        "grant_revoke": ("POST", f"/grants/{g['id']}/revoke", {"reason": "not yours"}),
        "draft": ("GET", f"/drafts/{d['id']}", None),
        "draft_publish": ("POST", f"/drafts/{d['id']}/publish", {}),
        "version": ("GET", "/versions/1", None),
        "rollback": ("POST", "/versions/1/rollback",
                     {"reason": "not yours", "expected_version": 1}),
    }
    seen = {k: (await api(m, p, b, who="outsider")).status_code for k, (m, p, b) in paths.items()}
    assert set(seen.values()) == {404}, seen
    for lst in ("/grants", "/drafts", "/versions", "/audit"):
        assert (await api("GET", lst, who="outsider")).json()["items"] == []
    obs.note(statuses=seen, lists_empty=True)
    obs.done()
