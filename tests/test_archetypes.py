"""Tests for NEXUS Agent Archetype Library.

Tests cover:
- AgentArchetype dataclass creation and field validation
- All 20 named archetype instances have populated fields
- ArchetypeRegistry auto-registration, lookup, listing, and filtering
- Field constraints (capabilities count, constraints count, interaction styles)
"""

import pytest

from nexus.templates.archetypes import (
    ACCESSIBILITY_SPECIALIST,
    BACKEND_ENGINEER,
    DATABASE_ADMIN,
    DATA_ENGINEER,
    DESIGNER,
    DEVOPS_ENGINEER,
    FRONTEND_ENGINEER,
    ML_ENGINEER,
    MOBILE_DEVELOPER,
    PERFORMANCE_ENGINEER,
    PRODUCT_MANAGER,
    PROJECT_MANAGER,
    QA_ENGINEER,
    RESEARCHER,
    SCRUM_MASTER,
    SECURITY_ENGINEER,
    SITE_RELIABILITY_ENGINEER,
    SOFTWARE_ARCHITECT,
    TEAM_LEAD,
    TECH_WRITER,
    AgentArchetype,
    ArchetypeRegistry,
    _ALL_ARCHETYPES,
)


VALID_INTERACTION_STYLES = {
    "collaborative",
    "directive",
    "analytical",
    "creative",
    "supportive",
    "methodical",
}


class TestAgentArchetypeDataclass:
    """Test AgentArchetype dataclass creation and field semantics."""

    def test_create_archetype_with_all_fields(self):
        """AgentArchetype can be created with all required fields."""
        archetype = AgentArchetype(
            name="Test Agent",
            role="test-agent",
            capabilities=["cap1", "cap2", "cap3"],
            constraints=["con1", "con2"],
            system_prompt="You are a test agent for unit testing.",
            tools_allowed=["tool1", "tool2"],
            interaction_style="collaborative",
            description="A test archetype for verification.",
        )

        assert archetype.name == "Test Agent"
        assert archetype.role == "test-agent"
        assert len(archetype.capabilities) == 3
        assert len(archetype.constraints) == 2
        assert "test agent" in archetype.system_prompt.lower()
        assert len(archetype.tools_allowed) == 2
        assert archetype.interaction_style == "collaborative"
        assert archetype.description != ""

    def test_archetype_is_frozen(self):
        """AgentArchetype instances are immutable (frozen dataclass)."""
        archetype = AgentArchetype(
            name="Frozen Test",
            role="frozen-test",
            capabilities=["cap1", "cap2", "cap3"],
            constraints=["con1", "con2"],
            system_prompt="You are frozen.",
            tools_allowed=["tool1", "tool2"],
            interaction_style="analytical",
            description="A frozen archetype.",
        )
        with pytest.raises(AttributeError):
            archetype.name = "New Name"  # type: ignore

    def test_archetype_default_values(self):
        """AgentArchetype has sensible defaults for optional fields."""
        archetype = AgentArchetype(name="Minimal", role="minimal")
        assert archetype.capabilities == []
        assert archetype.constraints == []
        assert archetype.system_prompt == ""
        assert archetype.tools_allowed == []
        assert archetype.interaction_style == "collaborative"
        assert archetype.description == ""


class TestAllArchetypesPopulated:
    """Verify all 20 named archetypes have required fields populated."""

    def test_all_20_archetypes_exist(self):
        """There are exactly 20 named archetype instances."""
        assert len(_ALL_ARCHETYPES) == 20

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_non_empty_name(self, archetype: AgentArchetype):
        """Each archetype has a non-empty name."""
        assert archetype.name != ""
        assert len(archetype.name) > 2

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_non_empty_role(self, archetype: AgentArchetype):
        """Each archetype has a non-empty kebab-case role."""
        assert archetype.role != ""
        assert "-" in archetype.role or archetype.role.islower()

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_3_plus_capabilities(self, archetype: AgentArchetype):
        """Each archetype has at least 3 capabilities."""
        assert len(archetype.capabilities) >= 3

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_2_plus_constraints(self, archetype: AgentArchetype):
        """Each archetype has at least 2 constraints."""
        assert len(archetype.constraints) >= 2

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_non_empty_system_prompt(self, archetype: AgentArchetype):
        """Each archetype has a multi-sentence system prompt."""
        assert archetype.system_prompt != ""
        assert len(archetype.system_prompt) > 50

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_tools_allowed(self, archetype: AgentArchetype):
        """Each archetype has at least 2 tools allowed."""
        assert len(archetype.tools_allowed) >= 2

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_valid_interaction_style(self, archetype: AgentArchetype):
        """Each archetype has a recognized interaction style."""
        assert archetype.interaction_style in VALID_INTERACTION_STYLES

    @pytest.mark.parametrize("archetype", _ALL_ARCHETYPES)
    def test_archetype_has_description(self, archetype: AgentArchetype):
        """Each archetype has a non-empty description."""
        assert archetype.description != ""
        assert len(archetype.description) > 10


class TestArchetypeRegistry:
    """Test ArchetypeRegistry auto-registration, lookup, and filtering."""

    @pytest.fixture
    def registry(self) -> ArchetypeRegistry:
        """Create an ArchetypeRegistry instance."""
        return ArchetypeRegistry()

    def test_registry_auto_registers_all_20(self, registry: ArchetypeRegistry):
        """ArchetypeRegistry auto-registers all 20 archetypes on init."""
        archetypes = registry.list_archetypes()
        assert len(archetypes) == 20

    def test_get_archetype_returns_correct(self, registry: ArchetypeRegistry):
        """get_archetype returns the matching archetype by name."""
        result = registry.get_archetype("Software Architect")
        assert result is not None
        assert result.role == "software-architect"
        assert result is SOFTWARE_ARCHITECT

    def test_get_archetype_returns_none_for_unknown(self, registry: ArchetypeRegistry):
        """get_archetype returns None for a name that does not exist."""
        result = registry.get_archetype("Nonexistent Role")
        assert result is None

    def test_list_archetypes_returns_all_20(self, registry: ArchetypeRegistry):
        """list_archetypes returns all 20 registered archetypes."""
        archetypes = registry.list_archetypes()
        assert len(archetypes) == 20
        names = [a.name for a in archetypes]
        assert "Backend Engineer" in names
        assert "Team Lead" in names

    def test_get_archetypes_by_role_found(self, registry: ArchetypeRegistry):
        """get_archetypes_by_role returns matching archetypes."""
        results = registry.get_archetypes_by_role("devops-engineer")
        assert len(results) == 1
        assert results[0].name == "DevOps Engineer"

    def test_get_archetypes_by_role_not_found(self, registry: ArchetypeRegistry):
        """get_archetypes_by_role returns empty list for unknown role."""
        results = registry.get_archetypes_by_role("unknown-role")
        assert results == []

    def test_each_archetype_accessible_by_name(self, registry: ArchetypeRegistry):
        """Every archetype can be retrieved by its name."""
        for archetype in _ALL_ARCHETYPES:
            result = registry.get_archetype(archetype.name)
            assert result is not None
            assert result.role == archetype.role
