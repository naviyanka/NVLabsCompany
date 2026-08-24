"""Pre-built team composition templates for batch hiring.

Each template defines a named team of agents with archetype assignments,
suggested names, default models, and a reporting hierarchy. Teams can be
deployed as-is or customized before creation.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TeamAgentSlot:
    """A slot in a team template representing one agent to hire.

    Attributes:
        archetype: Archetype name from ArchetypeRegistry (e.g. "Backend Engineer").
        suggested_name: Default agent name (user can override).
        default_provider: CLI provider id (e.g. "claude", "codex").
        default_model: Model to use (empty string = provider default).
        reports_to_index: Index of the manager agent in the same template
            (-1 = no manager / top-level).
        title_override: Custom title if different from archetype name.
    """

    archetype: str
    suggested_name: str
    default_provider: str = "claude"
    default_model: str = ""
    reports_to_index: int = -1
    title_override: str = ""


@dataclass(frozen=True)
class TeamTemplate:
    """A pre-built team composition template.

    Attributes:
        id: Kebab-case identifier.
        name: Display name.
        description: 1-2 sentence explanation of the team's purpose.
        icon: Emoji or icon identifier for the UI.
        agents: Ordered list of agent slots to hire.
        tags: Category tags for filtering.
    """

    id: str
    name: str
    description: str
    icon: str = "👥"
    agents: list[TeamAgentSlot] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Pre-built Team Templates
# ---------------------------------------------------------------------------

STARTUP_MVP_SQUAD = TeamTemplate(
    id="startup-mvp",
    name="Startup MVP Squad",
    description=(
        "Ship a product from zero to production. Full-stack team with "
        "architecture, implementation, quality, and deployment."
    ),
    icon="🚀",
    tags=["full-stack", "startup", "mvp"],
    agents=[
        TeamAgentSlot(
            archetype="Software Architect",
            suggested_name="Arch-01",
            default_provider="claude",
            title_override="Lead Architect",
            reports_to_index=-1,
        ),
        TeamAgentSlot(
            archetype="Backend Engineer",
            suggested_name="Bolt-02",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Frontend Engineer",
            suggested_name="Pixel-03",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="QA Engineer",
            suggested_name="Shield-04",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="DevOps Engineer",
            suggested_name="Forge-05",
            default_provider="claude",
            reports_to_index=0,
        ),
    ],
)

CORE_PRODUCT_TEAM = TeamTemplate(
    id="core-product",
    name="Core Product Team",
    description=(
        "Feature development team with product thinking, design, "
        "full-stack engineering, and quality assurance."
    ),
    icon="📦",
    tags=["product", "features", "design"],
    agents=[
        TeamAgentSlot(
            archetype="Product Manager",
            suggested_name="Compass-01",
            default_provider="claude",
            title_override="Product Lead",
            reports_to_index=-1,
        ),
        TeamAgentSlot(
            archetype="Designer",
            suggested_name="Prism-02",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Frontend Engineer",
            suggested_name="Pixel-03",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Backend Engineer",
            suggested_name="Bolt-04",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="QA Engineer",
            suggested_name="Shield-05",
            default_provider="claude",
            reports_to_index=0,
        ),
    ],
)

PLATFORM_INFRA_TEAM = TeamTemplate(
    id="platform-infra",
    name="Platform & Infrastructure",
    description=(
        "Reliability, security, and infrastructure team. Handles CI/CD, "
        "monitoring, databases, and security posture."
    ),
    icon="🏗️",
    tags=["infra", "platform", "reliability", "security"],
    agents=[
        TeamAgentSlot(
            archetype="DevOps Engineer",
            suggested_name="Forge-01",
            default_provider="claude",
            title_override="Platform Lead",
            reports_to_index=-1,
        ),
        TeamAgentSlot(
            archetype="Site Reliability Engineer",
            suggested_name="Uptime-02",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Database Administrator",
            suggested_name="Vault-03",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Security Engineer",
            suggested_name="Sentinel-04",
            default_provider="claude",
            reports_to_index=0,
        ),
    ],
)

ML_DATA_TEAM = TeamTemplate(
    id="ml-data",
    name="ML & Data Team",
    description=(
        "Machine learning and data infrastructure. Covers model development, "
        "data pipelines, and research experimentation."
    ),
    icon="🧠",
    tags=["ml", "data", "research", "ai"],
    agents=[
        TeamAgentSlot(
            archetype="ML Engineer",
            suggested_name="Sage-01",
            default_provider="claude",
            title_override="ML Lead",
            reports_to_index=-1,
        ),
        TeamAgentSlot(
            archetype="Data Engineer",
            suggested_name="Flow-02",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Researcher",
            suggested_name="Lens-03",
            default_provider="claude",
            reports_to_index=0,
        ),
    ],
)

LEADERSHIP_TEAM = TeamTemplate(
    id="leadership",
    name="Leadership & Coordination",
    description=(
        "Strategy and coordination layer. Architecture decisions, project "
        "management, agile practices, and technical leadership."
    ),
    icon="👔",
    tags=["leadership", "management", "strategy"],
    agents=[
        TeamAgentSlot(
            archetype="Team Lead",
            suggested_name="Atlas-01",
            default_provider="claude",
            title_override="Engineering Director",
            reports_to_index=-1,
        ),
        TeamAgentSlot(
            archetype="Software Architect",
            suggested_name="Blueprint-02",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Project Manager",
            suggested_name="Compass-03",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Scrum Master",
            suggested_name="Sprint-04",
            default_provider="claude",
            reports_to_index=0,
        ),
    ],
)

FULL_COMPANY = TeamTemplate(
    id="full-company",
    name="Full Company (8 Agents)",
    description=(
        "Complete autonomous organization: executive leadership, engineering, "
        "research, operations, and quality. Based on the NEXUS demo configuration."
    ),
    icon="🏢",
    tags=["full", "company", "complete", "demo"],
    agents=[
        TeamAgentSlot(
            archetype="Team Lead",
            suggested_name="Atlas",
            default_provider="claude",
            title_override="Chief Executive Officer",
            reports_to_index=-1,
        ),
        TeamAgentSlot(
            archetype="Software Architect",
            suggested_name="Nova",
            default_provider="claude",
            title_override="Chief Technology Officer",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Backend Engineer",
            suggested_name="Bolt",
            default_provider="claude",
            reports_to_index=1,
        ),
        TeamAgentSlot(
            archetype="Frontend Engineer",
            suggested_name="Pixel",
            default_provider="claude",
            reports_to_index=1,
        ),
        TeamAgentSlot(
            archetype="Researcher",
            suggested_name="Sage",
            default_provider="claude",
            title_override="AI Research Lead",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="Project Manager",
            suggested_name="Compass",
            default_provider="claude",
            reports_to_index=0,
        ),
        TeamAgentSlot(
            archetype="QA Engineer",
            suggested_name="Shield",
            default_provider="claude",
            reports_to_index=1,
        ),
        TeamAgentSlot(
            archetype="DevOps Engineer",
            suggested_name="Forge",
            default_provider="claude",
            reports_to_index=1,
        ),
    ],
)


# All templates as a module-level list
ALL_TEAM_TEMPLATES: list[TeamTemplate] = [
    STARTUP_MVP_SQUAD,
    CORE_PRODUCT_TEAM,
    PLATFORM_INFRA_TEAM,
    ML_DATA_TEAM,
    LEADERSHIP_TEAM,
    FULL_COMPANY,
]


def get_team_template(template_id: str) -> TeamTemplate | None:
    """Look up a team template by its ID.

    Args:
        template_id: The kebab-case template identifier.

    Returns:
        The TeamTemplate if found, None otherwise.
    """
    for t in ALL_TEAM_TEMPLATES:
        if t.id == template_id:
            return t
    return None


def list_team_templates() -> list[TeamTemplate]:
    """Return all available team templates."""
    return list(ALL_TEAM_TEMPLATES)
