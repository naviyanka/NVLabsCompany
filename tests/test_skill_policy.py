"""Tests for Phase 5.4 - versioned skill access policy."""

import pytest

from nexus.governance.skill_policy import (
    SCHEMA_VERSION,
    SkillRef,
    SkillSubject,
    decision,
)

INTERN = SkillSubject(agent_id="agent-1", roles=("intern",))
LEAD = SkillSubject(agent_id="agent-2", roles=("lead",))
CATALOG_SKILL = SkillRef(id="sk-1", key="web-scraper", source_type="catalog")
LOCAL_SKILL = SkillRef(id="sk-2", key="local-lint", source_type="local")


def _policy(rules: list[dict], **kw: object) -> dict:
    doc = {
        "schemaVersion": SCHEMA_VERSION,
        "revision": 7,
        "defaultEffect": "allow",
        "rules": rules,
    }
    doc.update(kw)
    return doc


def test_absent_policy_allows() -> None:
    """5.4.4 - no policy document means open by default."""
    for empty in (None, {}):
        d = decision(empty, INTERN, CATALOG_SKILL)
        assert d.allowed is True
        assert d.effect == "allow"
        assert d.matched_rule is None
        assert d.remediation == ""


def test_deny_by_role_and_source_type_carries_remediation() -> None:
    """5.4.2/5.4.3 - role subject + source_type resource, remediation on deny."""
    policy = _policy(
        [
            {
                "id": "no-community-for-interns",
                "effect": "deny",
                "subject": {"roles": ["intern"]},
                "resource": {"source_types": ["catalog"]},
                "reason": "Interns may not run community skills.",
                "remediation": "Ask an admin to vendor the skill locally.",
            }
        ]
    )

    denied = decision(policy, INTERN, CATALOG_SKILL)
    assert denied.allowed is False
    assert denied.effect == "deny"
    assert denied.reason == "Interns may not run community skills."
    assert denied.remediation == "Ask an admin to vendor the skill locally."
    assert denied.matched_rule_index == 0
    assert denied.revision == 7

    # Same subject, non-matching resource -> falls through to defaultEffect.
    assert decision(policy, INTERN, LOCAL_SKILL).allowed is True
    # Same resource, non-matching subject.
    assert decision(policy, LEAD, CATALOG_SKILL).allowed is True


def test_deny_default_has_remediation_and_revision() -> None:
    """A closed policy still explains itself and names its revision."""
    d = decision(_policy([], defaultEffect="deny"), LEAD, LOCAL_SKILL)
    assert d.allowed is False
    assert d.matched_rule is None
    assert d.revision == 7
    assert d.remediation


def test_first_matching_rule_wins_and_can_allow() -> None:
    """Document order decides; an allow rule can shadow a later blanket deny."""
    policy = _policy(
        [
            {
                "effect": "allow",
                "subject": {"agent_ids": ["agent-1"]},
                "resource": {"skill_ids": ["sk-1"]},
            },
            {"effect": "deny", "subject": {"all": True}},
        ]
    )
    allowed = decision(policy, INTERN, CATALOG_SKILL)
    assert allowed.allowed is True
    assert allowed.matched_rule_index == 0
    assert allowed.remediation == ""

    # Anyone else hits the blanket deny.
    assert decision(policy, LEAD, LOCAL_SKILL).matched_rule_index == 1


def test_key_globs_and_disabled_rules() -> None:
    """Keys match by glob; disabled rules are skipped."""
    policy = _policy(
        [
            {"effect": "deny", "resource": {"keys": ["local-*"]}, "enabled": False},
            {"effect": "deny", "resource": {"keys": ["web-*"]}},
        ]
    )
    assert decision(policy, LEAD, LOCAL_SKILL).allowed is True
    assert decision(policy, LEAD, CATALOG_SKILL).allowed is False


def test_bad_schema_version_and_effect_raise() -> None:
    """A document this build cannot read is an error, not a silent allow."""
    with pytest.raises(ValueError, match="schemaVersion"):
        decision(_policy([], schemaVersion=99), LEAD, LOCAL_SKILL)
    with pytest.raises(ValueError, match="defaultEffect"):
        decision(_policy([], defaultEffect="maybe"), LEAD, LOCAL_SKILL)
