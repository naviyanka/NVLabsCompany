"""Identity management API endpoints.

Provides endpoints for managing agent souls, soul templates,
and working context assembly.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

router = APIRouter(tags=["identity"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class SoulResponse(BaseModel):
    """Response model for an agent's soul definition."""

    agent_id: str
    name: str
    role: str
    personality_traits: list[str] = []
    communication_style: str = ""
    expertise: list[str] = []
    values: list[str] = []
    constraints: list[str] = []
    background: str = ""
    tone: str = "professional"


class SoulUpdateRequest(BaseModel):
    """Request body for updating an agent's soul."""

    name: str | None = None
    role: str | None = None
    personality_traits: list[str] | None = None
    communication_style: str | None = None
    expertise: list[str] | None = None
    values: list[str] | None = None
    constraints: list[str] | None = None
    background: str | None = None
    tone: str | None = None


class SoulTemplateResponse(BaseModel):
    """Response model for a soul template."""

    template_id: str
    name: str
    description: str
    default_role: str
    personality_traits: list[str] = []
    expertise: list[str] = []


class BuildContextRequest(BaseModel):
    """Request body for building an agent's working context."""

    total_tokens: int = 4096
    identity_weight: float = 0.25
    memory_weight: float = 0.25
    task_weight: float = 0.50
    task_context: dict[str, Any] | None = None


class WorkingContextResponse(BaseModel):
    """Response model for an assembled working context."""

    agent_id: str
    system_prompt: str
    total_tokens: int = 0
    memory_count: int = 0
    task_context: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# In-memory state for demo purposes
# ---------------------------------------------------------------------------

_agent_souls: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/agents/{agent_id}/soul",
    response_model=SoulResponse,
)
async def get_agent_soul(agent_id: uuid.UUID) -> dict[str, Any]:
    """Get the soul definition for an agent.

    Args:
        agent_id: The agent whose soul to retrieve.

    Returns:
        The agent's soul definition.

    Raises:
        HTTPException: If no soul is found for this agent.
    """
    agent_id_str = str(agent_id)
    soul_data = _agent_souls.get(agent_id_str)

    if soul_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No soul found for agent {agent_id}",
        )

    return {
        "agent_id": agent_id_str,
        **soul_data,
    }


@router.put(
    "/api/v1/agents/{agent_id}/soul",
    response_model=SoulResponse,
)
async def update_agent_soul(
    agent_id: uuid.UUID, body: SoulUpdateRequest
) -> dict[str, Any]:
    """Update an agent's soul definition.

    Creates the soul if it does not exist, or updates existing fields.
    Only fields explicitly provided in the request body are updated.

    Args:
        agent_id: The agent whose soul to update.
        body: The soul fields to update.

    Returns:
        The updated soul definition.
    """
    agent_id_str = str(agent_id)
    existing = _agent_souls.get(agent_id_str, {})

    # Apply updates from request body
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        existing[key] = value

    # Ensure defaults for missing fields
    existing.setdefault("name", "")
    existing.setdefault("role", "")
    existing.setdefault("personality_traits", [])
    existing.setdefault("communication_style", "")
    existing.setdefault("expertise", [])
    existing.setdefault("values", [])
    existing.setdefault("constraints", [])
    existing.setdefault("background", "")
    existing.setdefault("tone", "professional")

    _agent_souls[agent_id_str] = existing

    return {
        "agent_id": agent_id_str,
        **existing,
    }


@router.get(
    "/api/v1/identity/templates",
    response_model=list[SoulTemplateResponse],
)
async def list_soul_templates() -> list[dict[str, Any]]:
    """List all available soul templates.

    Returns the pre-built soul templates that can be used to create
    agent identities for common organizational roles.

    Returns:
        List of soul template summaries.
    """
    # Template definitions matching SOUL_TEMPLATES in identity.soul
    templates = [
        {
            "template_id": "engineer",
            "name": "Software Engineer",
            "description": "Detail-oriented engineer focused on code quality and implementation.",
            "default_role": "senior_software_engineer",
            "personality_traits": ["detail-oriented", "methodical", "pragmatic", "collaborative"],
            "expertise": [
                "software architecture",
                "code review",
                "debugging",
                "performance optimization",
                "testing strategies",
            ],
        },
        {
            "template_id": "researcher",
            "name": "Research Analyst",
            "description": "Analytical researcher focused on thorough investigation and evidence.",
            "default_role": "research_analyst",
            "personality_traits": ["analytical", "thorough", "curious", "skeptical", "systematic"],
            "expertise": [
                "literature review",
                "data analysis",
                "methodology design",
                "technical writing",
                "comparative analysis",
            ],
        },
        {
            "template_id": "manager",
            "name": "Project Manager",
            "description": "Strategic manager focused on delegation, coordination, and delivery.",
            "default_role": "project_manager",
            "personality_traits": ["strategic", "delegating", "communicative", "decisive", "organized"],
            "expertise": [
                "project planning",
                "team coordination",
                "risk management",
                "stakeholder communication",
                "resource allocation",
            ],
        },
        {
            "template_id": "qa_engineer",
            "name": "QA Engineer",
            "description": "Meticulous QA engineer focused on testing and quality assurance.",
            "default_role": "qa_engineer",
            "personality_traits": ["meticulous", "systematic", "skeptical", "persistent", "observant"],
            "expertise": [
                "test strategy",
                "test automation",
                "regression testing",
                "edge case identification",
                "bug reporting",
                "performance testing",
            ],
        },
        {
            "template_id": "architect",
            "name": "System Architect",
            "description": "Big-picture architect focused on system design and technical strategy.",
            "default_role": "system_architect",
            "personality_traits": ["visionary", "analytical", "pragmatic", "communicative", "patient"],
            "expertise": [
                "system design",
                "distributed systems",
                "API design",
                "scalability patterns",
                "technology evaluation",
                "technical debt management",
            ],
        },
    ]
    return templates


@router.post(
    "/api/v1/agents/{agent_id}/context",
    response_model=WorkingContextResponse,
)
async def build_working_context(
    agent_id: uuid.UUID, body: BuildContextRequest
) -> dict[str, Any]:
    """Build a working context for an agent.

    Assembles the agent's identity (soul), recent memories, and task
    context within the specified token budget.

    Args:
        agent_id: The agent to build context for.
        body: Context budget parameters.

    Returns:
        The assembled working context with system prompt and token usage.

    Raises:
        HTTPException: If no soul is found for this agent.
    """
    agent_id_str = str(agent_id)
    soul_data = _agent_souls.get(agent_id_str)

    if soul_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No soul found for agent {agent_id}. "
            "Create a soul first via PUT /api/v1/agents/{agent_id}/soul",
        )

    # Build a system prompt from the soul data
    sections: list[str] = []

    name = soul_data.get("name", "")
    role = soul_data.get("role", "")
    if name or role:
        identity_parts: list[str] = []
        if name:
            identity_parts.append(f"You are {name}")
        if role:
            identity_parts.append(
                f"{'serving as' if name else 'You are'} a {role}"
            )
        sections.append(". ".join(identity_parts) + ".")

    traits = soul_data.get("personality_traits", [])
    if traits:
        sections.append(f"Personality: You are {', '.join(traits)}.")

    style = soul_data.get("communication_style", "")
    if style:
        sections.append(f"Communication style: {style}")

    expertise = soul_data.get("expertise", [])
    if expertise:
        sections.append(f"Expertise: {', '.join(expertise)}.")

    values = soul_data.get("values", [])
    if values:
        sections.append(f"Core values: You prioritize {', '.join(values)}.")

    system_prompt = "\n\n".join(sections)

    # Estimate token usage
    total_tokens_used = max(1, len(system_prompt) // 4)

    return {
        "agent_id": agent_id_str,
        "system_prompt": system_prompt,
        "total_tokens": total_tokens_used,
        "memory_count": 0,
        "task_context": body.task_context,
    }
