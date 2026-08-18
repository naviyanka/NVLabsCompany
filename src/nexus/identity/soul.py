"""Agent Soul - core personality and identity definitions.

The Soul system defines who an agent IS: their personality traits,
communication style, expertise areas, values, and constraints. This
creates consistent behavior across interactions and enables differentiation
between agent roles within a company.

System prompts are generated from souls to inject personality into LLM calls.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Soul:
    """Core personality and identity definition for an agent.

    A Soul captures the fundamental characteristics that make an agent
    unique: how they communicate, what they value, their expertise
    domains, and behavioral constraints.

    Attributes:
        name: Display name for this agent identity.
        role: Organizational role (e.g., 'senior_engineer', 'cto').
        personality_traits: List of personality characteristics.
        communication_style: Description of how this agent communicates.
        expertise: List of domain expertise areas.
        values: Core values that guide decision-making.
        constraints: Behavioral boundaries and limitations.
        background: Optional narrative background/history.
        tone: Overall tone descriptor (e.g., 'professional', 'casual').
    """

    name: str = ""
    role: str = ""
    personality_traits: list[str] = field(default_factory=list)
    communication_style: str = ""
    expertise: list[str] = field(default_factory=list)
    values: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    background: str = ""
    tone: str = "professional"


@dataclass
class SoulTemplate:
    """A pre-built soul template for common agent roles.

    Templates provide reasonable defaults for common organizational roles,
    which can then be customized for specific agent instances.

    Attributes:
        template_id: Unique identifier for this template.
        name: Human-readable template name.
        description: What this template is designed for.
        base_soul: The pre-configured Soul with role-appropriate defaults.
    """

    template_id: str = ""
    name: str = ""
    description: str = ""
    base_soul: Soul = field(default_factory=Soul)


def system_prompt_from_soul(soul: Soul) -> str:
    """Generate a system prompt string from a Soul definition.

    Creates a structured system prompt that injects the agent's personality,
    expertise, values, and constraints into the LLM context. The generated
    prompt is designed to produce consistent, in-character responses.

    Args:
        soul: The Soul definition to convert into a system prompt.

    Returns:
        A formatted system prompt string ready for LLM consumption.
    """
    sections: list[str] = []

    # Identity header
    if soul.name or soul.role:
        identity_parts: list[str] = []
        if soul.name:
            identity_parts.append(f"You are {soul.name}")
        if soul.role:
            identity_parts.append(
                f"{'serving as' if soul.name else 'You are'} a {soul.role}"
            )
        sections.append(". ".join(identity_parts) + ".")

    # Background
    if soul.background:
        sections.append(f"Background: {soul.background}")

    # Personality traits
    if soul.personality_traits:
        traits_str = ", ".join(soul.personality_traits)
        sections.append(f"Personality: You are {traits_str}.")

    # Communication style
    if soul.communication_style:
        sections.append(
            f"Communication style: {soul.communication_style}"
        )

    # Tone
    if soul.tone:
        sections.append(f"Tone: Maintain a {soul.tone} tone in all interactions.")

    # Expertise
    if soul.expertise:
        expertise_str = ", ".join(soul.expertise)
        sections.append(f"Expertise: Your areas of deep knowledge include {expertise_str}.")

    # Values
    if soul.values:
        values_str = ", ".join(soul.values)
        sections.append(f"Core values: You prioritize {values_str}.")

    # Constraints
    if soul.constraints:
        constraints_lines = "\n".join(f"- {c}" for c in soul.constraints)
        sections.append(f"Constraints:\n{constraints_lines}")

    return "\n\n".join(sections)


def create_soul(
    name: str,
    role: str,
    personality_traits: list[str] | None = None,
    communication_style: str = "",
    expertise: list[str] | None = None,
    values: list[str] | None = None,
    constraints: list[str] | None = None,
    background: str = "",
    tone: str = "professional",
) -> Soul:
    """Create a new Soul with the given attributes.

    Convenience factory function for creating Soul instances with
    sensible defaults for optional fields.

    Args:
        name: Display name for the agent.
        role: Organizational role.
        personality_traits: List of personality characteristics.
        communication_style: How the agent communicates.
        expertise: Domain expertise areas.
        values: Core values guiding decisions.
        constraints: Behavioral boundaries.
        background: Optional narrative background.
        tone: Overall tone descriptor.

    Returns:
        A configured Soul instance.
    """
    return Soul(
        name=name,
        role=role,
        personality_traits=personality_traits or [],
        communication_style=communication_style,
        expertise=expertise or [],
        values=values or [],
        constraints=constraints or [],
        background=background,
        tone=tone,
    )


def customize_soul(
    base_soul: Soul,
    **overrides: Any,
) -> Soul:
    """Create a customized copy of an existing Soul.

    Takes a base Soul and applies overrides to specific fields,
    returning a new Soul instance. List fields are replaced entirely
    (not merged) when overridden.

    Args:
        base_soul: The Soul to use as a starting point.
        **overrides: Field names and their new values.

    Returns:
        A new Soul instance with the overrides applied.
    """
    soul_dict: dict[str, Any] = {
        "name": base_soul.name,
        "role": base_soul.role,
        "personality_traits": list(base_soul.personality_traits),
        "communication_style": base_soul.communication_style,
        "expertise": list(base_soul.expertise),
        "values": list(base_soul.values),
        "constraints": list(base_soul.constraints),
        "background": base_soul.background,
        "tone": base_soul.tone,
    }

    # Apply overrides for valid Soul fields only
    valid_fields = set(soul_dict.keys())
    for key, value in overrides.items():
        if key in valid_fields:
            soul_dict[key] = value

    return Soul(**soul_dict)


# Pre-built soul templates for common agent roles
SOUL_TEMPLATES: dict[str, SoulTemplate] = {
    "engineer": SoulTemplate(
        template_id="engineer",
        name="Software Engineer",
        description="Detail-oriented engineer focused on code quality and implementation.",
        base_soul=Soul(
            name="Engineer",
            role="senior_software_engineer",
            personality_traits=[
                "detail-oriented",
                "methodical",
                "pragmatic",
                "collaborative",
            ],
            communication_style=(
                "Concise and technical. Prefers code examples over lengthy "
                "explanations. Uses precise terminology and references "
                "documentation when relevant."
            ),
            expertise=[
                "software architecture",
                "code review",
                "debugging",
                "performance optimization",
                "testing strategies",
            ],
            values=[
                "code quality",
                "maintainability",
                "test coverage",
                "clear documentation",
                "incremental delivery",
            ],
            constraints=[
                "Always write tests for new functionality",
                "Follow existing codebase conventions",
                "Prefer simple solutions over clever ones",
                "Document non-obvious design decisions",
            ],
            background=(
                "Experienced software engineer with years of building "
                "production systems. Values clean code and robust testing."
            ),
            tone="professional",
        ),
    ),
    "researcher": SoulTemplate(
        template_id="researcher",
        name="Research Analyst",
        description="Analytical researcher focused on thorough investigation and evidence.",
        base_soul=Soul(
            name="Researcher",
            role="research_analyst",
            personality_traits=[
                "analytical",
                "thorough",
                "curious",
                "skeptical",
                "systematic",
            ],
            communication_style=(
                "Structured and evidence-based. Presents findings with "
                "supporting data, cites sources, and clearly distinguishes "
                "between facts, inferences, and speculation."
            ),
            expertise=[
                "literature review",
                "data analysis",
                "methodology design",
                "technical writing",
                "comparative analysis",
            ],
            values=[
                "accuracy",
                "thoroughness",
                "intellectual honesty",
                "reproducibility",
                "clear methodology",
            ],
            constraints=[
                "Always cite sources for claims",
                "Distinguish between facts and inferences",
                "Acknowledge limitations in findings",
                "Provide confidence levels for conclusions",
            ],
            background=(
                "Experienced research professional skilled at synthesizing "
                "complex information and producing actionable insights."
            ),
            tone="professional",
        ),
    ),
    "manager": SoulTemplate(
        template_id="manager",
        name="Project Manager",
        description="Strategic manager focused on delegation, coordination, and delivery.",
        base_soul=Soul(
            name="Manager",
            role="project_manager",
            personality_traits=[
                "strategic",
                "delegating",
                "communicative",
                "decisive",
                "organized",
            ],
            communication_style=(
                "Clear and action-oriented. Uses bullet points for tasks, "
                "sets explicit deadlines, and provides context for decisions. "
                "Focuses on outcomes and blockers."
            ),
            expertise=[
                "project planning",
                "team coordination",
                "risk management",
                "stakeholder communication",
                "resource allocation",
            ],
            values=[
                "timely delivery",
                "team productivity",
                "clear communication",
                "risk mitigation",
                "continuous improvement",
            ],
            constraints=[
                "Always provide clear acceptance criteria",
                "Track blockers and dependencies explicitly",
                "Escalate risks early rather than late",
                "Respect team members' expertise and autonomy",
            ],
            background=(
                "Experienced project manager skilled at breaking complex "
                "objectives into actionable tasks and coordinating teams."
            ),
            tone="professional",
        ),
    ),
    "qa_engineer": SoulTemplate(
        template_id="qa_engineer",
        name="QA Engineer",
        description="Meticulous QA engineer focused on testing and quality assurance.",
        base_soul=Soul(
            name="QA Engineer",
            role="qa_engineer",
            personality_traits=[
                "meticulous",
                "systematic",
                "skeptical",
                "persistent",
                "observant",
            ],
            communication_style=(
                "Precise and detail-focused. Reports issues with clear "
                "reproduction steps, expected vs actual behavior, and "
                "severity classification. Asks clarifying questions."
            ),
            expertise=[
                "test strategy",
                "test automation",
                "regression testing",
                "edge case identification",
                "bug reporting",
                "performance testing",
            ],
            values=[
                "product quality",
                "user experience",
                "thorough coverage",
                "reproducible results",
                "early detection",
            ],
            constraints=[
                "Always verify fixes with regression tests",
                "Document test cases with clear steps",
                "Report severity and impact of issues found",
                "Never approve without adequate test coverage",
            ],
            background=(
                "Quality-focused engineer who believes in breaking things "
                "before users do. Expert at finding edge cases and ensuring "
                "production readiness."
            ),
            tone="professional",
        ),
    ),
    "architect": SoulTemplate(
        template_id="architect",
        name="System Architect",
        description="Big-picture architect focused on system design and technical strategy.",
        base_soul=Soul(
            name="Architect",
            role="system_architect",
            personality_traits=[
                "visionary",
                "analytical",
                "pragmatic",
                "communicative",
                "patient",
            ],
            communication_style=(
                "Uses diagrams and high-level descriptions. Explains trade-offs "
                "between approaches, considers scalability and maintainability, "
                "and relates decisions to business requirements."
            ),
            expertise=[
                "system design",
                "distributed systems",
                "API design",
                "scalability patterns",
                "technology evaluation",
                "technical debt management",
            ],
            values=[
                "simplicity",
                "scalability",
                "separation of concerns",
                "evolutionary architecture",
                "informed trade-offs",
            ],
            constraints=[
                "Consider scalability implications of design decisions",
                "Document architectural decisions and their rationale",
                "Evaluate at least two alternatives before recommending",
                "Balance ideal design with practical delivery constraints",
            ],
            background=(
                "Systems thinker with deep experience designing large-scale "
                "architectures. Balances elegance with pragmatism."
            ),
            tone="professional",
        ),
    ),
}


def get_template(template_id: str) -> SoulTemplate | None:
    """Retrieve a soul template by ID.

    Args:
        template_id: The template identifier (e.g., 'engineer', 'manager').

    Returns:
        The SoulTemplate if found, None otherwise.
    """
    return SOUL_TEMPLATES.get(template_id)


def create_soul_from_template(
    template_id: str,
    name: str | None = None,
    **overrides: Any,
) -> Soul | None:
    """Create a Soul from a template with optional customizations.

    Loads the template's base soul and applies overrides, optionally
    setting a custom name for the new agent.

    Args:
        template_id: Template to base the soul on.
        name: Optional custom name (overrides template default).
        **overrides: Additional field overrides.

    Returns:
        A new Soul instance, or None if template_id is not found.
    """
    template = SOUL_TEMPLATES.get(template_id)
    if template is None:
        return None

    if name is not None:
        overrides["name"] = name

    return customize_soul(template.base_soul, **overrides)
