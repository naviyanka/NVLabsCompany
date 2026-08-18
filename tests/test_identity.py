"""Tests for NEXUS Agent Identity System - soul generation, context assembly.

Tests cover:
- Soul dataclass creation with all fields
- System prompt generation from Soul
- SOUL_TEMPLATES with all 5 expected roles
- create_soul factory function
- customize_soul modification
- Persona working context assembly
- Context budget allocation
- Memory truncation under budget
- save_persona and load_persona round-trip
- Memory namespace isolation between agents
"""

import pytest

from nexus.identity.soul import (
    Soul,
    SoulTemplate,
    SOUL_TEMPLATES,
    system_prompt_from_soul,
    create_soul,
    customize_soul,
    create_soul_from_template,
    get_template,
)
from nexus.identity.persona import (
    Persona,
    ContextBudget,
    WorkingContext,
    allocate_budget,
    _estimate_tokens,
    _truncate_to_tokens,
)


class TestSoul:
    """Test Soul dataclass and related factory functions."""

    def test_soul_creation_all_fields(self):
        """Soul dataclass accepts all fields correctly."""
        soul = Soul(
            name="TestBot",
            role="engineer",
            personality_traits=["analytical", "focused"],
            communication_style="Concise and technical.",
            expertise=["Python", "testing"],
            values=["quality", "clarity"],
            constraints=["No shortcuts"],
            background="Built for testing.",
            tone="professional",
        )

        assert soul.name == "TestBot"
        assert soul.role == "engineer"
        assert soul.personality_traits == ["analytical", "focused"]
        assert soul.communication_style == "Concise and technical."
        assert soul.expertise == ["Python", "testing"]
        assert soul.values == ["quality", "clarity"]
        assert soul.constraints == ["No shortcuts"]
        assert soul.background == "Built for testing."
        assert soul.tone == "professional"

    def test_soul_defaults(self):
        """Soul has reasonable defaults for optional fields."""
        soul = Soul()

        assert soul.name == ""
        assert soul.role == ""
        assert soul.personality_traits == []
        assert soul.communication_style == ""
        assert soul.expertise == []
        assert soul.values == []
        assert soul.constraints == []
        assert soul.background == ""
        assert soul.tone == "professional"

    def test_system_prompt_from_soul_contains_role(self):
        """system_prompt_from_soul includes the role in output."""
        soul = Soul(name="Forge", role="senior_engineer")

        prompt = system_prompt_from_soul(soul)

        assert "Forge" in prompt
        assert "senior_engineer" in prompt

    def test_system_prompt_from_soul_contains_traits(self):
        """system_prompt_from_soul includes personality traits."""
        soul = Soul(
            name="TestAgent",
            role="tester",
            personality_traits=["meticulous", "thorough"],
        )

        prompt = system_prompt_from_soul(soul)

        assert "meticulous" in prompt
        assert "thorough" in prompt

    def test_system_prompt_from_soul_contains_style(self):
        """system_prompt_from_soul includes communication style."""
        soul = Soul(
            name="Writer",
            role="writer",
            communication_style="Verbose and descriptive.",
        )

        prompt = system_prompt_from_soul(soul)

        assert "Verbose and descriptive" in prompt

    def test_system_prompt_from_soul_contains_expertise(self):
        """system_prompt_from_soul includes expertise areas."""
        soul = Soul(
            name="Expert",
            role="specialist",
            expertise=["machine learning", "distributed systems"],
        )

        prompt = system_prompt_from_soul(soul)

        assert "machine learning" in prompt
        assert "distributed systems" in prompt

    def test_system_prompt_from_soul_contains_values(self):
        """system_prompt_from_soul includes core values."""
        soul = Soul(
            name="Valued",
            role="leader",
            values=["transparency", "fairness"],
        )

        prompt = system_prompt_from_soul(soul)

        assert "transparency" in prompt
        assert "fairness" in prompt

    def test_system_prompt_from_soul_contains_constraints(self):
        """system_prompt_from_soul includes constraints."""
        soul = Soul(
            name="Constrained",
            role="worker",
            constraints=["Never skip tests", "Always document code"],
        )

        prompt = system_prompt_from_soul(soul)

        assert "Never skip tests" in prompt
        assert "Always document code" in prompt

    def test_system_prompt_from_soul_contains_tone(self):
        """system_prompt_from_soul includes tone directive."""
        soul = Soul(name="Casual", role="chat", tone="casual")

        prompt = system_prompt_from_soul(soul)

        assert "casual" in prompt

    def test_soul_templates_has_all_five(self):
        """SOUL_TEMPLATES contains all 5 expected templates."""
        expected_keys = {"engineer", "researcher", "manager", "qa_engineer", "architect"}

        assert set(SOUL_TEMPLATES.keys()) == expected_keys

    def test_soul_templates_are_soul_template_instances(self):
        """Each template is a SoulTemplate with a valid base_soul."""
        for key, template in SOUL_TEMPLATES.items():
            assert isinstance(template, SoulTemplate)
            assert isinstance(template.base_soul, Soul)
            assert template.template_id == key
            assert template.base_soul.name != ""
            assert template.base_soul.role != ""

    def test_create_soul_with_defaults(self):
        """create_soul creates a Soul with minimal required args."""
        soul = create_soul(name="Agent", role="worker")

        assert soul.name == "Agent"
        assert soul.role == "worker"
        assert soul.personality_traits == []
        assert soul.tone == "professional"

    def test_create_soul_with_all_args(self):
        """create_soul creates a Soul with all optional args provided."""
        soul = create_soul(
            name="Full",
            role="architect",
            personality_traits=["creative"],
            communication_style="Visual",
            expertise=["design"],
            values=["simplicity"],
            constraints=["Stay focused"],
            background="Design background.",
            tone="casual",
        )

        assert soul.personality_traits == ["creative"]
        assert soul.communication_style == "Visual"
        assert soul.expertise == ["design"]
        assert soul.values == ["simplicity"]
        assert soul.constraints == ["Stay focused"]
        assert soul.background == "Design background."
        assert soul.tone == "casual"

    def test_customize_soul_modifies_fields(self):
        """customize_soul returns new Soul with specified overrides."""
        base = create_soul(
            name="Original",
            role="engineer",
            personality_traits=["focused"],
            expertise=["Python"],
        )

        customized = customize_soul(
            base,
            name="Modified",
            expertise=["Rust", "Go"],
        )

        assert customized.name == "Modified"
        assert customized.expertise == ["Rust", "Go"]
        # Unchanged fields remain
        assert customized.role == "engineer"
        assert customized.personality_traits == ["focused"]

    def test_customize_soul_does_not_mutate_original(self):
        """customize_soul leaves the original Soul unmodified."""
        base = create_soul(name="Stable", role="engineer", expertise=["Python"])

        customize_soul(base, name="Changed", expertise=["Java"])

        assert base.name == "Stable"
        assert base.expertise == ["Python"]

    def test_customize_soul_ignores_invalid_fields(self):
        """customize_soul ignores fields not present on Soul."""
        base = create_soul(name="Test", role="tester")

        customized = customize_soul(base, nonexistent_field="ignored")

        assert customized.name == "Test"
        assert customized.role == "tester"

    def test_create_soul_from_template(self):
        """create_soul_from_template creates soul with template defaults."""
        soul = create_soul_from_template("engineer", name="MyEngineer")

        assert soul is not None
        assert soul.name == "MyEngineer"
        assert soul.role == "senior_software_engineer"
        assert len(soul.personality_traits) > 0
        assert len(soul.expertise) > 0

    def test_create_soul_from_template_unknown_returns_none(self):
        """create_soul_from_template returns None for unknown template."""
        result = create_soul_from_template("nonexistent_template")
        assert result is None

    def test_get_template(self):
        """get_template retrieves correct template by ID."""
        template = get_template("manager")
        assert template is not None
        assert template.template_id == "manager"
        assert template.base_soul.role == "project_manager"


class TestPersona:
    """Test Persona context assembly, budgets, persistence."""

    @pytest.fixture(autouse=True)
    def clear_store(self):
        """Clear the persona store before each test."""
        Persona.clear_store()
        yield
        Persona.clear_store()

    def test_persona_creation(self):
        """Persona initializes with agent_id and namespace."""
        persona = Persona("agent-1", namespace="ns_agent_1")

        assert persona.agent_id == "agent-1"
        assert persona.memory_namespace == "ns_agent_1"

    def test_persona_default_namespace(self):
        """Persona uses agent_id-based namespace by default."""
        persona = Persona("agent-2")

        assert persona.memory_namespace == "agent_agent-2"

    def test_build_working_context_assembles_all_parts(self):
        """build_working_context produces a WorkingContext with all components."""
        soul = create_soul(
            name="TestAgent",
            role="engineer",
            personality_traits=["focused"],
            expertise=["Python"],
        )
        persona = Persona("agent-1")
        persona.soul = soul
        persona.add_memory({"content": "Did task A", "timestamp": "2024-01-01"})

        ctx = persona.build_working_context(
            task={"objective": "Build API", "priority": "high"},
        )

        assert isinstance(ctx, WorkingContext)
        assert ctx.soul == soul
        assert "TestAgent" in ctx.system_prompt
        assert "engineer" in ctx.system_prompt
        assert len(ctx.recent_memories) >= 1
        assert ctx.task_context["objective"] == "Build API"
        assert ctx.total_tokens > 0

    def test_context_budget_allocation_proportional(self):
        """allocate_budget splits tokens proportionally by weights."""
        budget = allocate_budget(
            total_tokens=8000,
            identity_weight=0.25,
            memory_weight=0.25,
            task_weight=0.50,
        )

        assert budget.total_tokens == 8000
        assert budget.identity_tokens == 2000
        assert budget.memory_tokens == 2000
        assert budget.task_tokens == 4000

    def test_context_budget_allocation_unequal_weights(self):
        """allocate_budget handles non-standard weight proportions."""
        budget = allocate_budget(
            total_tokens=10000,
            identity_weight=0.1,
            memory_weight=0.3,
            task_weight=0.6,
        )

        assert budget.total_tokens == 10000
        assert budget.identity_tokens == 1000
        assert budget.memory_tokens == 3000
        assert budget.task_tokens == 6000

    def test_context_budget_allocation_normalizes_weights(self):
        """allocate_budget normalizes weights that do not sum to 1.0."""
        budget = allocate_budget(
            total_tokens=1000,
            identity_weight=1.0,
            memory_weight=1.0,
            task_weight=2.0,
        )

        # 1/4, 1/4, 2/4
        assert budget.identity_tokens == 250
        assert budget.memory_tokens == 250
        assert budget.task_tokens == 500

    def test_memory_truncation_when_over_budget(self):
        """build_working_context truncates memories that exceed budget."""
        persona = Persona("agent-trunc")
        soul = create_soul(name="Small", role="worker")
        persona.soul = soul

        # Add many large memories
        for i in range(100):
            persona.add_memory({
                "content": f"Memory entry {i} with some extra text to consume tokens " * 10,
                "idx": i,
            })

        # Use a very small memory budget
        budget = ContextBudget(
            total_tokens=2000,
            identity_tokens=500,
            memory_tokens=100,  # Very small - will truncate
            task_tokens=1400,
        )

        ctx = persona.build_working_context(budget=budget)

        # Should have fewer memories than we added
        assert len(ctx.recent_memories) < 100

    def test_save_and_load_persona_round_trip(self):
        """save_persona and load_persona preserve soul and memories."""
        persona = Persona("agent-save")
        soul = create_soul(
            name="Persistent",
            role="archivist",
            personality_traits=["organized"],
            expertise=["data management"],
        )
        persona.soul = soul
        persona.add_memory({"content": "Important fact", "type": "knowledge"})
        persona.add_memory({"content": "Task completed", "type": "event"})

        persona.save_persona()

        loaded = Persona.load_persona("agent-save")

        assert loaded is not None
        assert loaded.agent_id == "agent-save"
        assert loaded.soul is not None
        assert loaded.soul.name == "Persistent"
        assert loaded.soul.role == "archivist"
        assert loaded.soul.personality_traits == ["organized"]
        assert loaded.soul.expertise == ["data management"]
        assert len(loaded._memories) == 2
        assert loaded._memories[0]["content"] == "Important fact"

    def test_load_persona_not_found(self):
        """load_persona returns None for unknown agent_id."""
        result = Persona.load_persona("nonexistent-agent")
        assert result is None

    def test_memory_namespace_isolation(self):
        """Two personas with different namespaces have independent memories."""
        persona_a = Persona("agent-a", namespace="ns_a")
        persona_b = Persona("agent-b", namespace="ns_b")

        persona_a.add_memory({"content": "A's memory"})
        persona_b.add_memory({"content": "B's memory"})

        assert persona_a.get_memories() == [{"content": "A's memory"}]
        assert persona_b.get_memories() == [{"content": "B's memory"}]

    def test_save_persona_isolation(self):
        """Saved personas are independent in the store."""
        persona_a = Persona("agent-x")
        persona_a.soul = create_soul(name="X", role="x_role")
        persona_a.add_memory({"data": "x"})
        persona_a.save_persona()

        persona_b = Persona("agent-y")
        persona_b.soul = create_soul(name="Y", role="y_role")
        persona_b.add_memory({"data": "y"})
        persona_b.save_persona()

        loaded_a = Persona.load_persona("agent-x")
        loaded_b = Persona.load_persona("agent-y")

        assert loaded_a.soul.name == "X"
        assert loaded_b.soul.name == "Y"
        assert loaded_a._memories[0]["data"] == "x"
        assert loaded_b._memories[0]["data"] == "y"

    def test_clear_memories(self):
        """clear_memories removes all memories from a persona."""
        persona = Persona("agent-clear")
        persona.add_memory({"content": "will be cleared"})
        assert len(persona.get_memories()) == 1

        persona.clear_memories()
        assert len(persona.get_memories()) == 0

    def test_build_working_context_with_explicit_budget(self):
        """build_working_context respects an explicitly provided budget."""
        persona = Persona("agent-budget")
        soul = create_soul(
            name="BudgetedAgent",
            role="worker",
            personality_traits=["efficient"],
        )

        budget = allocate_budget(
            total_tokens=4096,
            identity_weight=0.3,
            memory_weight=0.2,
            task_weight=0.5,
        )

        ctx = persona.build_working_context(
            soul=soul,
            memories=[{"content": "task history"}],
            task={"objective": "Test the budget system"},
            budget=budget,
        )

        assert ctx.total_tokens <= budget.total_tokens
        assert "BudgetedAgent" in ctx.system_prompt

    def test_estimate_tokens(self):
        """_estimate_tokens uses ~4 chars per token heuristic."""
        assert _estimate_tokens("") == 0
        assert _estimate_tokens("abcd") == 1
        assert _estimate_tokens("a" * 100) == 25

    def test_truncate_to_tokens(self):
        """_truncate_to_tokens limits text to fit within token budget."""
        long_text = "x" * 1000  # ~250 tokens
        truncated = _truncate_to_tokens(long_text, max_tokens=50)

        # 50 tokens * 4 chars = 200 chars + "..."
        assert len(truncated) <= 203
        assert truncated.endswith("...")

    def test_truncate_to_tokens_short_text(self):
        """_truncate_to_tokens returns text unchanged if within budget."""
        short_text = "hello"
        result = _truncate_to_tokens(short_text, max_tokens=100)
        assert result == "hello"
