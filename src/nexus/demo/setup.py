"""Demo Company Setup - idempotent bootstrapper for NexusCorp.

Creates a fully configured demo company with agents, departments,
budget policies, approval gates, skill assignments, and tool access
permissions. Safe to run multiple times (returns existing setup if
already initialized).
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from nexus.identity.soul import (
    Soul,
    create_soul_from_template,
    customize_soul,
    SOUL_TEMPLATES,
)


# Deterministic UUID generation for idempotency (uuid5 with DNS namespace)
_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _deterministic_id(name: str) -> uuid.UUID:
    """Generate a deterministic UUID from a name for idempotent setup.

    Args:
        name: The seed name for UUID generation.

    Returns:
        A UUID5 derived from the name.
    """
    return uuid.uuid5(_NAMESPACE, name)


@dataclass
class AgentConfig:
    """Configuration for a demo agent.

    Attributes:
        agent_id: Deterministic UUID for this agent.
        name: Agent display name.
        role: Organizational role.
        soul: Soul definition for this agent.
        adapter_type: LLM adapter to use.
        model: Model name/identifier.
        manager_id: UUID of the managing agent (None for CEO).
        capabilities: List of capability strings.
        department: Department assignment.
    """

    agent_id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    role: str = ""
    soul: Soul = field(default_factory=Soul)
    adapter_type: str = ""
    model: str = ""
    manager_id: uuid.UUID | None = None
    capabilities: list[str] = field(default_factory=list)
    department: str = ""


@dataclass
class Department:
    """A demo department within the company.

    Attributes:
        department_id: Deterministic UUID for this department.
        name: Department name.
        lead_agent_id: UUID of the department lead.
        member_ids: List of member agent UUIDs.
    """

    department_id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    lead_agent_id: uuid.UUID | None = None
    member_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class BudgetPolicy:
    """Budget policy for the demo company.

    Attributes:
        scope_type: 'company' or 'agent'.
        scope_id: UUID of the entity this policy applies to.
        monthly_limit_cents: Maximum spend per month in cents.
        alert_threshold_percent: Percentage at which to alert.
    """

    scope_type: str = ""
    scope_id: uuid.UUID = field(default_factory=uuid.uuid4)
    monthly_limit_cents: int = 0
    alert_threshold_percent: float = 80.0


@dataclass
class ApprovalGate:
    """Approval gate configuration.

    Attributes:
        gate_type: Type of action requiring approval.
        approver_id: UUID of the agent who must approve.
        description: Human-readable description of when this gate applies.
    """

    gate_type: str = ""
    approver_id: uuid.UUID = field(default_factory=uuid.uuid4)
    description: str = ""


@dataclass
class SkillAssignment:
    """Skill assignment for an agent.

    Attributes:
        agent_id: UUID of the agent with this skill.
        skill_name: Name of the skill.
        proficiency: Proficiency level (0.0 to 1.0).
    """

    agent_id: uuid.UUID = field(default_factory=uuid.uuid4)
    skill_name: str = ""
    proficiency: float = 1.0


@dataclass
class ToolPermission:
    """Tool access permission for an agent.

    Attributes:
        agent_id: UUID of the agent granted access.
        tool_name: Name of the tool.
        access_level: Level of access ('read', 'write', 'execute').
    """

    agent_id: uuid.UUID = field(default_factory=uuid.uuid4)
    tool_name: str = ""
    access_level: str = "execute"


@dataclass
class DemoCompany:
    """Complete demo company configuration.

    Contains all references needed to interact with the demo setup:
    agents, departments, budget policies, approval gates, skills, and
    tool permissions.

    Attributes:
        company_id: Deterministic UUID for NexusCorp.
        company_name: The company name.
        agents: Dictionary of agent name to AgentConfig.
        departments: Dictionary of department name to Department.
        budget_policies: List of budget policies.
        approval_gates: List of approval gates.
        skill_assignments: List of skill assignments.
        tool_permissions: List of tool permissions.
    """

    company_id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_name: str = "NexusCorp"
    agents: dict[str, AgentConfig] = field(default_factory=dict)
    departments: dict[str, Department] = field(default_factory=dict)
    budget_policies: list[BudgetPolicy] = field(default_factory=list)
    approval_gates: list[ApprovalGate] = field(default_factory=list)
    skill_assignments: list[SkillAssignment] = field(default_factory=list)
    tool_permissions: list[ToolPermission] = field(default_factory=list)


# Module-level cache for idempotency
_demo_company: DemoCompany | None = None


def setup_demo_company() -> DemoCompany:
    """Set up the demo company NexusCorp with full organizational structure.

    This function is idempotent - calling it multiple times returns the same
    DemoCompany instance without re-creating anything.

    Creates:
        - NexusCorp company with deterministic UUID
        - CEO agent (Atlas) - high-level strategy, anthropic adapter
        - CTO agent (Nova) - technical planning, anthropic adapter
        - Senior Engineer agent (Forge) - implementation, openai adapter
        - Junior Engineer agent (Spark) - simple tasks, ollama adapter
        - QA agent (Shield) - testing/review, openai adapter
        - Departments: Engineering, QA
        - Budget policies (company + per-agent)
        - Approval gates (deployment requires CEO approval)
        - Skill assignments
        - Tool access permissions

    Returns:
        A DemoCompany dataclass with all references to the created entities.
    """
    global _demo_company

    # Idempotency check - return existing if already set up
    if _demo_company is not None:
        return _demo_company

    # Deterministic IDs for all entities
    company_id = _deterministic_id("NexusCorp")
    ceo_id = _deterministic_id("NexusCorp-Atlas-CEO")
    cto_id = _deterministic_id("NexusCorp-Nova-CTO")
    senior_eng_id = _deterministic_id("NexusCorp-Forge-SeniorEngineer")
    junior_eng_id = _deterministic_id("NexusCorp-Spark-JuniorEngineer")
    qa_id = _deterministic_id("NexusCorp-Shield-QA")
    eng_dept_id = _deterministic_id("NexusCorp-Engineering")
    qa_dept_id = _deterministic_id("NexusCorp-QA")

    # Create agent souls from templates
    ceo_soul = create_soul_from_template(
        "manager",
        name="Atlas",
        role="ceo",
        personality_traits=["strategic", "visionary", "decisive", "authoritative"],
        expertise=[
            "corporate strategy",
            "stakeholder management",
            "resource allocation",
            "high-level decision making",
        ],
    )

    cto_soul = create_soul_from_template(
        "architect",
        name="Nova",
        role="cto",
        personality_traits=["visionary", "technical", "analytical", "collaborative"],
        expertise=[
            "system architecture",
            "technical strategy",
            "team leadership",
            "technology evaluation",
            "scalability planning",
        ],
    )

    senior_eng_soul = create_soul_from_template(
        "engineer",
        name="Forge",
        role="senior_engineer",
        personality_traits=["detail-oriented", "experienced", "mentoring", "pragmatic"],
        expertise=[
            "full-stack development",
            "code architecture",
            "performance optimization",
            "code review",
            "mentoring",
        ],
    )

    junior_eng_soul = create_soul_from_template(
        "engineer",
        name="Spark",
        role="junior_engineer",
        personality_traits=["eager", "curious", "fast-learning", "enthusiastic"],
        expertise=[
            "basic programming",
            "simple task execution",
            "code formatting",
            "test writing",
        ],
        communication_style=(
            "Enthusiastic and question-oriented. Asks for clarification "
            "when unsure and reports progress frequently."
        ),
        constraints=[
            "Ask for guidance on complex decisions",
            "Follow senior engineer patterns",
            "Escalate when blocked for more than one attempt",
            "Focus on small, well-defined tasks",
        ],
    )

    qa_soul = create_soul_from_template(
        "qa_engineer",
        name="Shield",
        role="qa_engineer",
        personality_traits=["meticulous", "thorough", "skeptical", "quality-focused"],
        expertise=[
            "test automation",
            "regression testing",
            "edge case identification",
            "performance testing",
            "security testing",
        ],
    )

    # Build agent configurations
    ceo_agent = AgentConfig(
        agent_id=ceo_id,
        name="Atlas",
        role="ceo",
        soul=ceo_soul or Soul(name="Atlas", role="ceo"),
        adapter_type="anthropic",
        model="claude-sonnet-4-20250514",
        manager_id=None,
        capabilities=[
            "strategic_planning",
            "decision_making",
            "resource_allocation",
            "delegation",
        ],
        department="Executive",
    )

    cto_agent = AgentConfig(
        agent_id=cto_id,
        name="Nova",
        role="cto",
        soul=cto_soul or Soul(name="Nova", role="cto"),
        adapter_type="anthropic",
        model="claude-sonnet-4-20250514",
        manager_id=ceo_id,
        capabilities=[
            "technical_planning",
            "architecture_design",
            "task_decomposition",
            "technical_review",
            "team_coordination",
        ],
        department="Engineering",
    )

    senior_eng_agent = AgentConfig(
        agent_id=senior_eng_id,
        name="Forge",
        role="senior_engineer",
        soul=senior_eng_soul or Soul(name="Forge", role="senior_engineer"),
        adapter_type="openai",
        model="gpt-4o",
        manager_id=cto_id,
        capabilities=[
            "code_generation",
            "code_review",
            "architecture_implementation",
            "debugging",
            "performance_optimization",
            "mentoring",
        ],
        department="Engineering",
    )

    junior_eng_agent = AgentConfig(
        agent_id=junior_eng_id,
        name="Spark",
        role="junior_engineer",
        soul=junior_eng_soul or Soul(name="Spark", role="junior_engineer"),
        adapter_type="ollama",
        model="codellama",
        manager_id=cto_id,
        capabilities=[
            "code_generation",
            "simple_tasks",
            "test_writing",
            "documentation",
        ],
        department="Engineering",
    )

    qa_agent = AgentConfig(
        agent_id=qa_id,
        name="Shield",
        role="qa_engineer",
        soul=qa_soul or Soul(name="Shield", role="qa_engineer"),
        adapter_type="openai",
        model="gpt-4o",
        manager_id=cto_id,
        capabilities=[
            "testing",
            "code_review",
            "quality_assurance",
            "regression_testing",
            "security_review",
        ],
        department="QA",
    )

    # Set up departments
    engineering_dept = Department(
        department_id=eng_dept_id,
        name="Engineering",
        lead_agent_id=cto_id,
        member_ids=[cto_id, senior_eng_id, junior_eng_id],
    )

    qa_dept = Department(
        department_id=qa_dept_id,
        name="QA",
        lead_agent_id=qa_id,
        member_ids=[qa_id],
    )

    # Set up budget policies
    budget_policies = [
        # Company-wide monthly budget: 500000 cents ($5000/month)
        BudgetPolicy(
            scope_type="company",
            scope_id=company_id,
            monthly_limit_cents=500000,
            alert_threshold_percent=80.0,
        ),
        # Per-agent monthly budget: 50000 cents ($500/month)
        BudgetPolicy(
            scope_type="agent",
            scope_id=ceo_id,
            monthly_limit_cents=50000,
            alert_threshold_percent=80.0,
        ),
        BudgetPolicy(
            scope_type="agent",
            scope_id=cto_id,
            monthly_limit_cents=50000,
            alert_threshold_percent=80.0,
        ),
        BudgetPolicy(
            scope_type="agent",
            scope_id=senior_eng_id,
            monthly_limit_cents=50000,
            alert_threshold_percent=80.0,
        ),
        BudgetPolicy(
            scope_type="agent",
            scope_id=junior_eng_id,
            monthly_limit_cents=50000,
            alert_threshold_percent=80.0,
        ),
        BudgetPolicy(
            scope_type="agent",
            scope_id=qa_id,
            monthly_limit_cents=50000,
            alert_threshold_percent=80.0,
        ),
    ]

    # Set up approval gates (deployment requires CEO approval)
    approval_gates = [
        ApprovalGate(
            gate_type="deployment",
            approver_id=ceo_id,
            description="All deployments require CEO (Atlas) approval",
        ),
        ApprovalGate(
            gate_type="large_spend",
            approver_id=ceo_id,
            description="Spending over 10000 cents requires CEO approval",
        ),
        ApprovalGate(
            gate_type="architecture_change",
            approver_id=cto_id,
            description="Architecture changes require CTO (Nova) approval",
        ),
    ]

    # Set up skill assignments
    skill_assignments = [
        # CEO skills
        SkillAssignment(agent_id=ceo_id, skill_name="strategic_planning", proficiency=1.0),
        SkillAssignment(agent_id=ceo_id, skill_name="delegation", proficiency=0.95),
        SkillAssignment(agent_id=ceo_id, skill_name="decision_making", proficiency=0.95),
        # CTO skills
        SkillAssignment(agent_id=cto_id, skill_name="architecture_design", proficiency=0.95),
        SkillAssignment(agent_id=cto_id, skill_name="task_decomposition", proficiency=0.9),
        SkillAssignment(agent_id=cto_id, skill_name="technical_review", proficiency=0.9),
        # Senior Engineer skills
        SkillAssignment(agent_id=senior_eng_id, skill_name="code_generation", proficiency=0.9),
        SkillAssignment(agent_id=senior_eng_id, skill_name="debugging", proficiency=0.85),
        SkillAssignment(agent_id=senior_eng_id, skill_name="code_review", proficiency=0.85),
        SkillAssignment(agent_id=senior_eng_id, skill_name="mentoring", proficiency=0.8),
        # Junior Engineer skills
        SkillAssignment(agent_id=junior_eng_id, skill_name="code_generation", proficiency=0.6),
        SkillAssignment(agent_id=junior_eng_id, skill_name="test_writing", proficiency=0.65),
        SkillAssignment(agent_id=junior_eng_id, skill_name="documentation", proficiency=0.7),
        # QA skills
        SkillAssignment(agent_id=qa_id, skill_name="testing", proficiency=0.95),
        SkillAssignment(agent_id=qa_id, skill_name="regression_testing", proficiency=0.9),
        SkillAssignment(agent_id=qa_id, skill_name="security_review", proficiency=0.8),
    ]

    # Set up tool access permissions
    tool_permissions = [
        # CEO: high-level tools
        ToolPermission(agent_id=ceo_id, tool_name="approval_engine", access_level="execute"),
        ToolPermission(agent_id=ceo_id, tool_name="budget_manager", access_level="execute"),
        ToolPermission(agent_id=ceo_id, tool_name="reporting_dashboard", access_level="read"),
        # CTO: planning and review tools
        ToolPermission(agent_id=cto_id, tool_name="task_planner", access_level="execute"),
        ToolPermission(agent_id=cto_id, tool_name="code_reviewer", access_level="execute"),
        ToolPermission(agent_id=cto_id, tool_name="architecture_diagrammer", access_level="execute"),
        # Senior Engineer: full development tools
        ToolPermission(agent_id=senior_eng_id, tool_name="code_editor", access_level="execute"),
        ToolPermission(agent_id=senior_eng_id, tool_name="terminal", access_level="execute"),
        ToolPermission(agent_id=senior_eng_id, tool_name="git", access_level="execute"),
        ToolPermission(agent_id=senior_eng_id, tool_name="debugger", access_level="execute"),
        # Junior Engineer: restricted development tools
        ToolPermission(agent_id=junior_eng_id, tool_name="code_editor", access_level="execute"),
        ToolPermission(agent_id=junior_eng_id, tool_name="terminal", access_level="read"),
        ToolPermission(agent_id=junior_eng_id, tool_name="git", access_level="read"),
        # QA: testing tools
        ToolPermission(agent_id=qa_id, tool_name="test_runner", access_level="execute"),
        ToolPermission(agent_id=qa_id, tool_name="code_reviewer", access_level="execute"),
        ToolPermission(agent_id=qa_id, tool_name="performance_profiler", access_level="execute"),
    ]

    # Assemble the complete demo company
    demo = DemoCompany(
        company_id=company_id,
        company_name="NexusCorp",
        agents={
            "Atlas": ceo_agent,
            "Nova": cto_agent,
            "Forge": senior_eng_agent,
            "Spark": junior_eng_agent,
            "Shield": qa_agent,
        },
        departments={
            "Engineering": engineering_dept,
            "QA": qa_dept,
        },
        budget_policies=budget_policies,
        approval_gates=approval_gates,
        skill_assignments=skill_assignments,
        tool_permissions=tool_permissions,
    )

    # Cache for idempotency
    _demo_company = demo
    return demo


def reset_demo_company() -> None:
    """Reset the demo company state (useful for testing).

    Clears the cached demo company so the next call to
    setup_demo_company() creates a fresh instance.
    """
    global _demo_company
    _demo_company = None
