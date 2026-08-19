"""Tests for the tool governance system: models, policy engine, profile resolver, and registry."""

import uuid

from nexus.models import (
    ToolCatalogEntry,
    ToolConnection,
    ToolPolicy,
    ToolProfile,
    ToolProfileBinding,
)
from nexus.tools.policy_engine import (
    PolicyDecision,
    PolicyRule,
    ProfileBinding,
    ProfileResolver,
    ToolPolicyEngine,
)
from nexus.tools.registry import CatalogEntry, ToolRegistry


class TestToolConnectionModel:
    """Tests for ToolConnection SQLModel instantiation."""

    def test_create_with_defaults(self) -> None:
        """ToolConnection can be created with minimal required fields."""
        conn = ToolConnection(
            company_id=uuid.uuid4(),
            name="My MCP Server",
            transport_type="mcp_remote",
        )
        assert conn.name == "My MCP Server"
        assert conn.transport_type == "mcp_remote"
        assert conn.auth_kind == "none"
        assert conn.health_status == "unknown"
        assert conn.is_active is True
        assert conn.endpoint_url is None
        assert conn.credential_ref is None
        assert conn.last_health_check_at is None

    def test_create_with_all_fields(self) -> None:
        """ToolConnection can be created with all fields specified."""
        company_id = uuid.uuid4()
        conn = ToolConnection(
            company_id=company_id,
            name="REST API Connection",
            transport_type="rest_api",
            endpoint_url="https://api.example.com/v1",
            auth_kind="bearer",
            credential_ref="vault://secrets/api-token",
            health_status="healthy",
            is_active=True,
        )
        assert conn.company_id == company_id
        assert conn.transport_type == "rest_api"
        assert conn.endpoint_url == "https://api.example.com/v1"
        assert conn.auth_kind == "bearer"
        assert conn.credential_ref == "vault://secrets/api-token"
        assert conn.health_status == "healthy"

    def test_id_auto_generated(self) -> None:
        """ToolConnection gets an auto-generated UUID id."""
        conn = ToolConnection(
            company_id=uuid.uuid4(),
            name="Test",
            transport_type="local_stdio",
        )
        assert conn.id is not None
        assert isinstance(conn.id, uuid.UUID)


class TestToolCatalogEntryModel:
    """Tests for ToolCatalogEntry SQLModel instantiation."""

    def test_create_with_defaults(self) -> None:
        """ToolCatalogEntry can be created with minimal required fields."""
        entry = ToolCatalogEntry(
            company_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            tool_name="file_read",
        )
        assert entry.tool_name == "file_read"
        assert entry.risk_level == "read"
        assert entry.is_active is True
        assert entry.display_name is None
        assert entry.description is None
        assert entry.input_schema is None
        assert entry.output_schema is None
        assert entry.version is None

    def test_create_with_schemas(self) -> None:
        """ToolCatalogEntry stores JSON schemas correctly."""
        input_schema = {"type": "object", "properties": {"path": {"type": "string"}}}
        output_schema = {"type": "object", "properties": {"content": {"type": "string"}}}
        entry = ToolCatalogEntry(
            company_id=uuid.uuid4(),
            connection_id=uuid.uuid4(),
            tool_name="file_write",
            display_name="Write File",
            description="Writes content to a file",
            risk_level="write",
            input_schema=input_schema,
            output_schema=output_schema,
            version="1.2.0",
        )
        assert entry.display_name == "Write File"
        assert entry.risk_level == "write"
        assert entry.input_schema == input_schema
        assert entry.output_schema == output_schema
        assert entry.version == "1.2.0"


class TestToolProfileModel:
    """Tests for ToolProfile SQLModel instantiation."""

    def test_create_with_defaults(self) -> None:
        """ToolProfile can be created with minimal required fields."""
        profile = ToolProfile(
            company_id=uuid.uuid4(),
            name="Default Profile",
        )
        assert profile.name == "Default Profile"
        assert profile.default_action == "allow"
        assert profile.is_active is True
        assert profile.description is None

    def test_create_deny_profile(self) -> None:
        """ToolProfile can be created with deny default action."""
        profile = ToolProfile(
            company_id=uuid.uuid4(),
            name="Restricted Profile",
            description="Denies by default",
            default_action="deny",
        )
        assert profile.default_action == "deny"
        assert profile.description == "Denies by default"


class TestToolProfileBindingModel:
    """Tests for ToolProfileBinding SQLModel instantiation."""

    def test_create_agent_binding(self) -> None:
        """ToolProfileBinding can target an agent."""
        binding = ToolProfileBinding(
            company_id=uuid.uuid4(),
            profile_id=uuid.uuid4(),
            target_type="agent",
            target_id=uuid.uuid4(),
            priority=10,
        )
        assert binding.target_type == "agent"
        assert binding.priority == 10

    def test_create_department_binding(self) -> None:
        """ToolProfileBinding can target a department."""
        binding = ToolProfileBinding(
            company_id=uuid.uuid4(),
            profile_id=uuid.uuid4(),
            target_type="department",
            target_id=uuid.uuid4(),
            priority=50,
        )
        assert binding.target_type == "department"
        assert binding.priority == 50

    def test_create_company_binding(self) -> None:
        """ToolProfileBinding can target a company."""
        binding = ToolProfileBinding(
            company_id=uuid.uuid4(),
            profile_id=uuid.uuid4(),
            target_type="company",
            target_id=uuid.uuid4(),
            priority=100,
        )
        assert binding.target_type == "company"
        assert binding.priority == 100


class TestToolPolicyModel:
    """Tests for ToolPolicy SQLModel instantiation."""

    def test_create_allow_policy(self) -> None:
        """ToolPolicy can be created with allow effect."""
        policy = ToolPolicy(
            company_id=uuid.uuid4(),
            name="Allow reads",
            priority=10,
            effect="allow",
            conditions={"risk_level": "read"},
        )
        assert policy.effect == "allow"
        assert policy.priority == 10
        assert policy.conditions == {"risk_level": "read"}
        assert policy.is_active is True

    def test_create_deny_policy(self) -> None:
        """ToolPolicy can be created with deny effect."""
        policy = ToolPolicy(
            company_id=uuid.uuid4(),
            name="Block destructive",
            description="Blocks all destructive tools",
            priority=1,
            effect="deny",
            conditions={"risk_level": "destructive"},
        )
        assert policy.effect == "deny"
        assert policy.description == "Blocks all destructive tools"

    def test_create_with_complex_conditions(self) -> None:
        """ToolPolicy supports complex JSON conditions."""
        conditions = {
            "risk_level": ["write", "destructive"],
            "tool_name": ["db_*", "file_delete"],
            "time_of_day": {"start": 9, "end": 17},
        }
        policy = ToolPolicy(
            company_id=uuid.uuid4(),
            name="Complex policy",
            priority=5,
            effect="deny",
            conditions=conditions,
        )
        assert policy.conditions == conditions


class TestToolPolicyEngine:
    """Tests for ToolPolicyEngine evaluation logic."""

    def test_allow_policy_matches(self) -> None:
        """Engine returns allow when an allow policy matches."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Allow reads",
            priority=10,
            effect="allow",
            conditions={"risk_level": "read"},
        )
        engine.load_policies([policy])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_read",
            risk_level="read",
        )
        assert decision.allowed is True
        assert decision.matched_policy_id == policy.id

    def test_deny_policy_matches(self) -> None:
        """Engine returns deny when a deny policy matches."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Block destructive",
            priority=1,
            effect="deny",
            conditions={"risk_level": "destructive"},
        )
        engine.load_policies([policy])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="db_drop",
            risk_level="destructive",
        )
        assert decision.allowed is False
        assert decision.matched_policy_id == policy.id

    def test_priority_ordering_first_match_wins(self) -> None:
        """Higher priority (lower number) policy wins over lower priority."""
        engine = ToolPolicyEngine()
        high_priority = PolicyRule(
            name="Deny all writes",
            priority=1,
            effect="deny",
            conditions={"risk_level": "write"},
        )
        low_priority = PolicyRule(
            name="Allow all writes",
            priority=100,
            effect="allow",
            conditions={"risk_level": "write"},
        )
        # Load in reverse order to verify sorting
        engine.load_policies([low_priority, high_priority])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_write",
            risk_level="write",
        )
        assert decision.allowed is False
        assert decision.matched_policy_id == high_priority.id

    def test_no_match_defaults_to_allow(self) -> None:
        """When no policy matches, default action is allow."""
        engine = ToolPolicyEngine(default_effect="allow")
        policy = PolicyRule(
            name="Block destructive",
            priority=1,
            effect="deny",
            conditions={"risk_level": "destructive"},
        )
        engine.load_policies([policy])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_read",
            risk_level="read",
        )
        assert decision.allowed is True
        assert decision.matched_policy_id is None

    def test_no_match_defaults_to_deny(self) -> None:
        """When no policy matches and default is deny, access is denied."""
        engine = ToolPolicyEngine(default_effect="deny")
        policy = PolicyRule(
            name="Allow reads only",
            priority=1,
            effect="allow",
            conditions={"risk_level": "read"},
        )
        engine.load_policies([policy])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_write",
            risk_level="write",
        )
        assert decision.allowed is False
        assert decision.matched_policy_id is None

    def test_tool_name_pattern_matching(self) -> None:
        """Engine supports glob patterns for tool_name conditions."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Block db tools",
            priority=1,
            effect="deny",
            conditions={"tool_name": "db_*"},
        )
        engine.load_policies([policy])

        # Matches pattern
        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="db_drop_table",
            risk_level="destructive",
        )
        assert decision.allowed is False

        # Does not match pattern
        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_read",
            risk_level="read",
        )
        assert decision.allowed is True

    def test_multiple_conditions_all_must_match(self) -> None:
        """All conditions in a policy must match for the policy to apply."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Deny destructive db tools",
            priority=1,
            effect="deny",
            conditions={"risk_level": "destructive", "tool_name": "db_*"},
        )
        engine.load_policies([policy])

        # Only risk_level matches, not tool_name
        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_delete",
            risk_level="destructive",
        )
        assert decision.allowed is True  # Does not match because tool_name fails

        # Both match
        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="db_drop",
            risk_level="destructive",
        )
        assert decision.allowed is False

    def test_inactive_policies_skipped(self) -> None:
        """Inactive policies are not evaluated."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Block all",
            priority=1,
            effect="deny",
            conditions={"risk_level": "read"},
            is_active=False,
        )
        engine.load_policies([policy])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="file_read",
            risk_level="read",
        )
        assert decision.allowed is True
        assert decision.matched_policy_id is None

    def test_time_of_day_condition(self) -> None:
        """Engine evaluates time_of_day conditions using context."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Block outside business hours",
            priority=1,
            effect="deny",
            conditions={"time_of_day": {"start": 9, "end": 17}},
        )
        engine.load_policies([policy])

        # Within business hours - matches
        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="any_tool",
            risk_level="read",
            context={"hour": 10},
        )
        assert decision.allowed is False  # Policy denies during business hours

        # Outside business hours - does not match
        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="any_tool",
            risk_level="read",
            context={"hour": 20},
        )
        assert decision.allowed is True  # No match, falls to default allow

    def test_policy_decision_reason(self) -> None:
        """PolicyDecision includes a human-readable reason."""
        engine = ToolPolicyEngine()
        policy = PolicyRule(
            name="Test Policy",
            priority=5,
            effect="allow",
            conditions={"risk_level": "read"},
        )
        engine.load_policies([policy])

        decision = engine.evaluate(
            agent_id=uuid.uuid4(),
            tool_name="test",
            risk_level="read",
        )
        assert "Test Policy" in decision.reason
        assert "priority 5" in decision.reason


class TestProfileResolver:
    """Tests for ProfileResolver resolution logic."""

    def test_agent_level_override(self) -> None:
        """Agent-level binding takes precedence when present."""
        resolver = ProfileResolver()
        agent_id = uuid.uuid4()
        dept_id = uuid.uuid4()
        company_id = uuid.uuid4()

        agent_binding = ProfileBinding(
            target_type="agent",
            target_id=agent_id,
            priority=10,
            default_action="deny",
        )
        dept_binding = ProfileBinding(
            target_type="department",
            target_id=dept_id,
            priority=50,
            default_action="allow",
        )
        company_binding = ProfileBinding(
            target_type="company",
            target_id=company_id,
            priority=100,
            default_action="allow",
        )
        resolver.load_bindings([company_binding, dept_binding, agent_binding])

        result = resolver.resolve(agent_id, department_id=dept_id, company_id=company_id)
        assert result is not None
        assert result.target_type == "agent"
        assert result.target_id == agent_id
        assert result.default_action == "deny"

    def test_department_fallback(self) -> None:
        """Department-level binding is used when no agent-level binding exists."""
        resolver = ProfileResolver()
        agent_id = uuid.uuid4()
        dept_id = uuid.uuid4()
        company_id = uuid.uuid4()

        dept_binding = ProfileBinding(
            target_type="department",
            target_id=dept_id,
            priority=50,
            default_action="deny",
        )
        company_binding = ProfileBinding(
            target_type="company",
            target_id=company_id,
            priority=100,
            default_action="allow",
        )
        resolver.load_bindings([company_binding, dept_binding])

        result = resolver.resolve(agent_id, department_id=dept_id, company_id=company_id)
        assert result is not None
        assert result.target_type == "department"
        assert result.target_id == dept_id

    def test_company_default(self) -> None:
        """Company-level binding is used as last resort."""
        resolver = ProfileResolver()
        agent_id = uuid.uuid4()
        company_id = uuid.uuid4()

        company_binding = ProfileBinding(
            target_type="company",
            target_id=company_id,
            priority=100,
            default_action="allow",
        )
        resolver.load_bindings([company_binding])

        result = resolver.resolve(agent_id, company_id=company_id)
        assert result is not None
        assert result.target_type == "company"
        assert result.target_id == company_id

    def test_no_matching_binding(self) -> None:
        """Returns None when no binding matches the agent's hierarchy."""
        resolver = ProfileResolver()
        agent_id = uuid.uuid4()
        other_agent_id = uuid.uuid4()

        binding = ProfileBinding(
            target_type="agent",
            target_id=other_agent_id,
            priority=10,
        )
        resolver.load_bindings([binding])

        result = resolver.resolve(agent_id)
        assert result is None

    def test_priority_within_same_level(self) -> None:
        """Within the same target level, the first match by priority wins."""
        resolver = ProfileResolver()
        agent_id = uuid.uuid4()

        high_priority = ProfileBinding(
            target_type="agent",
            target_id=agent_id,
            priority=1,
            default_action="deny",
        )
        low_priority = ProfileBinding(
            target_type="agent",
            target_id=agent_id,
            priority=99,
            default_action="allow",
        )
        resolver.load_bindings([low_priority, high_priority])

        result = resolver.resolve(agent_id)
        assert result is not None
        assert result.priority == 1
        assert result.default_action == "deny"


class TestRegistryCatalogEntries:
    """Tests for ToolRegistry catalog entry methods."""

    def test_register_catalog_entry(self) -> None:
        """Can register and retrieve a catalog entry."""
        registry = ToolRegistry()
        company_id = uuid.uuid4()
        connection_id = uuid.uuid4()

        entry = CatalogEntry(
            company_id=company_id,
            connection_id=connection_id,
            tool_name="file_read",
            display_name="Read File",
            risk_level="read",
        )
        result = registry.register_catalog_entry(entry)
        assert result.id == entry.id
        assert result.tool_name == "file_read"

    def test_discover_from_connection(self) -> None:
        """discover_from_connection returns entries for a specific connection."""
        registry = ToolRegistry()
        company_id = uuid.uuid4()
        conn1 = uuid.uuid4()
        conn2 = uuid.uuid4()

        entry1 = CatalogEntry(
            company_id=company_id, connection_id=conn1, tool_name="tool_a"
        )
        entry2 = CatalogEntry(
            company_id=company_id, connection_id=conn1, tool_name="tool_b"
        )
        entry3 = CatalogEntry(
            company_id=company_id, connection_id=conn2, tool_name="tool_c"
        )

        registry.register_catalog_entry(entry1)
        registry.register_catalog_entry(entry2)
        registry.register_catalog_entry(entry3)

        results = registry.discover_from_connection(conn1)
        assert len(results) == 2
        names = {e.tool_name for e in results}
        assert names == {"tool_a", "tool_b"}

    def test_discover_from_connection_excludes_inactive(self) -> None:
        """discover_from_connection excludes inactive entries."""
        registry = ToolRegistry()
        conn_id = uuid.uuid4()

        active = CatalogEntry(
            company_id=uuid.uuid4(),
            connection_id=conn_id,
            tool_name="active_tool",
            is_active=True,
        )
        inactive = CatalogEntry(
            company_id=uuid.uuid4(),
            connection_id=conn_id,
            tool_name="inactive_tool",
            is_active=False,
        )

        registry.register_catalog_entry(active)
        registry.register_catalog_entry(inactive)

        results = registry.discover_from_connection(conn_id)
        assert len(results) == 1
        assert results[0].tool_name == "active_tool"

    def test_list_catalog_entries_no_filters(self) -> None:
        """list_catalog_entries returns all active entries when no filters applied."""
        registry = ToolRegistry()
        company_id = uuid.uuid4()

        for name in ["tool_1", "tool_2", "tool_3"]:
            registry.register_catalog_entry(
                CatalogEntry(
                    company_id=company_id,
                    connection_id=uuid.uuid4(),
                    tool_name=name,
                )
            )

        results = registry.list_catalog_entries()
        assert len(results) == 3

    def test_list_catalog_entries_filter_by_company(self) -> None:
        """list_catalog_entries filters by company_id."""
        registry = ToolRegistry()
        company_a = uuid.uuid4()
        company_b = uuid.uuid4()

        registry.register_catalog_entry(
            CatalogEntry(company_id=company_a, connection_id=uuid.uuid4(), tool_name="a")
        )
        registry.register_catalog_entry(
            CatalogEntry(company_id=company_b, connection_id=uuid.uuid4(), tool_name="b")
        )

        results = registry.list_catalog_entries(company_id=company_a)
        assert len(results) == 1
        assert results[0].tool_name == "a"

    def test_list_catalog_entries_filter_by_risk_level(self) -> None:
        """list_catalog_entries filters by risk_level."""
        registry = ToolRegistry()
        company_id = uuid.uuid4()

        registry.register_catalog_entry(
            CatalogEntry(
                company_id=company_id,
                connection_id=uuid.uuid4(),
                tool_name="reader",
                risk_level="read",
            )
        )
        registry.register_catalog_entry(
            CatalogEntry(
                company_id=company_id,
                connection_id=uuid.uuid4(),
                tool_name="writer",
                risk_level="write",
            )
        )
        registry.register_catalog_entry(
            CatalogEntry(
                company_id=company_id,
                connection_id=uuid.uuid4(),
                tool_name="destroyer",
                risk_level="destructive",
            )
        )

        results = registry.list_catalog_entries(risk_level="write")
        assert len(results) == 1
        assert results[0].tool_name == "writer"

    def test_list_catalog_entries_filter_by_connection(self) -> None:
        """list_catalog_entries filters by connection_id."""
        registry = ToolRegistry()
        conn_a = uuid.uuid4()
        conn_b = uuid.uuid4()
        company_id = uuid.uuid4()

        registry.register_catalog_entry(
            CatalogEntry(company_id=company_id, connection_id=conn_a, tool_name="from_a")
        )
        registry.register_catalog_entry(
            CatalogEntry(company_id=company_id, connection_id=conn_b, tool_name="from_b")
        )

        results = registry.list_catalog_entries(connection_id=conn_a)
        assert len(results) == 1
        assert results[0].tool_name == "from_a"

    def test_list_catalog_entries_combined_filters(self) -> None:
        """list_catalog_entries combines multiple filters."""
        registry = ToolRegistry()
        company_id = uuid.uuid4()
        conn_id = uuid.uuid4()

        registry.register_catalog_entry(
            CatalogEntry(
                company_id=company_id,
                connection_id=conn_id,
                tool_name="target",
                risk_level="write",
            )
        )
        registry.register_catalog_entry(
            CatalogEntry(
                company_id=company_id,
                connection_id=conn_id,
                tool_name="not_target",
                risk_level="read",
            )
        )
        registry.register_catalog_entry(
            CatalogEntry(
                company_id=uuid.uuid4(),
                connection_id=conn_id,
                tool_name="wrong_company",
                risk_level="write",
            )
        )

        results = registry.list_catalog_entries(
            company_id=company_id, risk_level="write", connection_id=conn_id
        )
        assert len(results) == 1
        assert results[0].tool_name == "target"
