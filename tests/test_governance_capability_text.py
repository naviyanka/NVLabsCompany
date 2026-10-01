"""Human-readable capability metadata: complete, presentation only, never an authorization key.

The golden file was captured from the catalogue before the text existed, so any change to an id
or an enforcement field fails here.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nexus.services.governance_studio import capability_text, catalog
from tests.test_governance_studio import _eff, _policy, api  # noqa: F401 -- fixtures and helpers
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures

GOLDEN = json.loads(
    (Path(__file__).parent / "golden_governance_catalog.json").read_text(encoding="utf-8")
)
RISKS = {"read", "write", "high", "low"}
SUPPORT = {"enforced", "approval_only", "display_only", "unsupported"}


class TestCompleteness:
    def test_all_44_capabilities_have_complete_metadata(self):
        caps = catalog.build_catalog()
        assert len(caps) == 44
        assert len({c["id"] for c in caps}) == 44
        for c in caps:
            assert c["display_name"].strip(), c["id"]
            assert len(c["description"].split()) >= 5, c["id"]
            assert c["description"] != capability_text.UNAVAILABLE, c["id"]
            assert c["category"] in catalog.CATEGORIES, c["id"]
            assert c["risk"] in RISKS, c["id"]
            assert c["support"] in SUPPORT, c["id"]
            assert c["display_name"] != c["id"] and c["display_name"] != c["tool_name"], c["id"]
            assert c["metadata_known"], c["id"]

    def test_names_start_with_a_verb_and_are_not_the_raw_identifier(self):
        for c in catalog.build_catalog():
            assert "_" not in c["display_name"] and "." not in c["display_name"], c["id"]
            assert c["display_name"][0].isupper(), c["id"]

    def test_the_text_table_covers_exactly_the_catalogue(self):
        assert set(capability_text._T) == {c["id"] for c in catalog.build_catalog()}

    def test_unsupported_capabilities_say_nexus_cannot_enforce_them(self):
        computer = [c for c in catalog.build_catalog() if c["support"] == "unsupported"]
        assert len(computer) == 4
        for c in computer:
            assert "cannot currently enforce" in c["description"]
            assert "cannot currently enforce" in c["limitations"]
            assert not c["toggleable"] and not c["approval_support"]

    def test_the_requested_examples_read_as_specified(self):
        by_id = catalog.catalog_by_id()
        assert by_id["org.ceo_list_pending_approvals"]["display_name"] == "View Pending Approvals"
        assert "does not allow the CEO to approve" in by_id[
            "org.ceo_list_pending_approvals"]["description"]
        assert by_id["org.ceo_request_hire"]["display_name"] == "Request a New Agent Hire"
        assert "does not bypass the required human approval" in by_id[
            "org.ceo_request_hire"]["description"]


class TestIdsAndEnforcementAreUnchanged:
    def test_technical_fields_match_the_pre_change_golden(self):
        keys = set(GOLDEN[0]) | {"bucket"}
        now = [{k: c[k] for k in keys if k in c} for c in catalog.build_catalog()]
        assert now == GOLDEN

    def test_registry_name_is_kept_for_existing_clients(self):
        for g, c in zip(GOLDEN, catalog.build_catalog(), strict=True):
            assert c["name"] == g["name"]


class TestFallback:
    def test_an_unknown_capability_gets_a_safe_fallback_and_keeps_its_state(self):
        d = capability_text.describe("tool.my-new_tool", "enforced")
        assert d["display_name"] == "My New Tool"
        assert d["description"] == "Description unavailable"
        assert d["metadata_known"] is False

    def test_the_fallback_never_changes_support_or_enforcement(self, monkeypatch):
        before = [{k: c[k] for k in ("support", "toggleable", "backends", "scope_schema")}
                  for c in catalog.build_catalog()]
        monkeypatch.setattr(capability_text, "_T", {})
        caps = catalog.build_catalog()
        assert all(c["description"] == "Description unavailable" for c in caps)
        assert [{k: c[k] for k in before[0]} for c in caps] == before

    def test_plain_explanation_falls_back_to_the_engine_wording(self):
        assert capability_text.plain_explanation("SOME_NEW_CODE", "denied", "engine said") == (
            "engine said")
        assert capability_text.plain_explanation("DEFAULT_DENY", "denied", "x") == (
            "No policy grants this capability, so the safe default is Deny.")


class TestDecisionsAreIndependentOfText:
    async def test_metadata_does_not_change_any_decision(self, factory, t, monkeypatch):  # noqa: F811
        await _policy(factory, t["acme"], name="no-http", effect="deny", priority=1,
                      conditions={"tool_name": ["http-request"]})
        keys = ("state", "decision", "code", "explanation", "source", "approval", "validity",
                "backend_support", "plain_explanation")
        with_text = {k: {f: v[f] for f in keys} for k, v in (await _eff(factory, t)).items()}
        monkeypatch.setattr(capability_text, "_T", {})
        without = {k: {f: v[f] for f in keys} for k, v in (await _eff(factory, t)).items()}
        assert with_text == without
        assert with_text["tool.http-request"]["code"] == "POLICY_DENY"

    async def test_every_decision_carries_a_plain_sentence_and_the_stable_code(
        self, factory, t,  # noqa: F811
    ):
        for cap in (await _eff(factory, t)).values():
            assert cap["code"] and cap["explanation"] and cap["plain_explanation"]
            assert cap["display_name"] and cap["id"]
        eff = await _eff(factory, t)
        assert eff["computer.browser"]["plain_explanation"].startswith("NEXUS cannot currently")
        assert eff["computer.browser"]["code"] == "NOT_ENFORCEABLE"


class TestDisplayNamesAreNotAuthorizationKeys:
    async def test_grant_and_simulator_reject_a_display_name(self, api, t):  # noqa: F811
        display = catalog.catalog_by_id()["tool.http-request"]["display_name"]
        expires = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        grant: dict[str, Any] = {"agent_id": str(t["a"]), "effect": "allow",
                                 "expires_at": expires, "reason": "metadata probe"}
        r = await api("POST", "/grants", {**grant, "tool_name": display})
        assert (r.status_code, r.json()["detail"]["code"]) == (422, "UNKNOWN_TOOL")
        r = await api("POST", "/simulate", {"agent_id": str(t["a"]), "capability_id": display})
        assert r.status_code >= 400
        r = await api("POST", "/simulate",
                      {"agent_id": str(t["a"]), "capability_id": "tool.http-request"})
        assert r.status_code == 200

    async def test_the_catalogue_and_matrix_endpoints_return_the_metadata(self, api, t):  # noqa: F811
        cat = (await api("GET", "/catalog")).json()["capabilities"]
        matrix = (await api("GET", f"/agents/{t['a']}/effective-access")).json()["capabilities"]
        for rows in (cat, matrix):
            assert len(rows) == 44
            for c in rows:
                assert c["id"] and c["display_name"] and c["description"]
                assert "limitations" in c and "examples" in c
