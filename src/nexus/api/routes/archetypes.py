"""Agent archetypes and templates API — exposes pre-built role templates for hiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter

from nexus.templates.archetypes import ArchetypeRegistry
from nexus.templates.registry import TemplateRegistry
from nexus.templates.team_templates import list_team_templates

router = APIRouter(tags=["archetypes"])

# Singleton registries — instantiated once at import time.
_archetype_registry = ArchetypeRegistry()
_template_registry = TemplateRegistry()

# Load markdown templates from the agents directory.
_TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates" / "agents"
if _TEMPLATES_DIR.exists():
    _template_registry.load_from_directory(_TEMPLATES_DIR)


@router.get("/api/v1/agent-archetypes")
async def list_agent_archetypes() -> list[dict[str, Any]]:
    """List all 20 pre-built agent role archetypes.

    Each archetype contains capabilities, constraints, system prompt,
    allowed tools, and interaction style — everything needed to instantiate
    a fully-configured agent from a template.
    """
    archetypes = _archetype_registry.list_archetypes()
    return [
        {
            "name": a.name,
            "role": a.role,
            "capabilities": a.capabilities,
            "constraints": a.constraints,
            "system_prompt": a.system_prompt,
            "tools_allowed": a.tools_allowed,
            "interaction_style": a.interaction_style,
            "description": a.description,
        }
        for a in archetypes
    ]


@router.get("/api/v1/agent-archetypes/{role}")
async def get_archetype_by_role(role: str) -> list[dict[str, Any]]:
    """Get archetypes matching a specific role identifier (kebab-case)."""
    archetypes = _archetype_registry.get_archetypes_by_role(role)
    return [
        {
            "name": a.name,
            "role": a.role,
            "capabilities": a.capabilities,
            "constraints": a.constraints,
            "system_prompt": a.system_prompt,
            "tools_allowed": a.tools_allowed,
            "interaction_style": a.interaction_style,
            "description": a.description,
        }
        for a in archetypes
    ]


@router.get("/api/v1/agent-templates")
async def list_agent_templates() -> list[dict[str, Any]]:
    """List available agent role templates (Markdown-based with YAML frontmatter).

    Templates provide detailed instructions, rules, and processes for each role.
    """
    templates = _template_registry.list_templates()
    return [
        {
            "name": t.name,
            "description": t.description,
            "file_path": t.file_path,
        }
        for t in templates
    ]


@router.get("/api/v1/agent-templates/{name}")
async def get_agent_template(name: str) -> dict[str, Any]:
    """Get full content of a specific agent template by name."""
    template = _template_registry.get_template(name)
    if template is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{name}' not found",
        )
    return {
        "name": template.name,
        "description": template.description,
        "body": template.body,
        "file_path": template.file_path,
    }



@router.get("/api/v1/team-templates")
async def list_all_team_templates() -> list[dict[str, Any]]:
    """List all pre-built team composition templates.

    Each template defines a named squad of agents with archetype assignments,
    suggested names, default providers, and a reporting hierarchy. Users can
    deploy a template as-is or customize it before batch-hiring.
    """
    templates = list_team_templates()
    return [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
            "icon": t.icon,
            "tags": t.tags,
            "agent_count": len(t.agents),
            "agents": [
                {
                    "archetype": slot.archetype,
                    "suggested_name": slot.suggested_name,
                    "default_provider": slot.default_provider,
                    "default_model": slot.default_model,
                    "reports_to_index": slot.reports_to_index,
                    "title_override": slot.title_override,
                }
                for slot in t.agents
            ],
        }
        for t in templates
    ]


@router.get("/api/v1/team-templates/{template_id}")
async def get_team_template_detail(template_id: str) -> dict[str, Any]:
    """Get a specific team template by ID."""
    from fastapi import HTTPException, status

    from nexus.templates.team_templates import get_team_template

    template = get_team_template(template_id)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Team template '{template_id}' not found",
        )
    return {
        "id": template.id,
        "name": template.name,
        "description": template.description,
        "icon": template.icon,
        "tags": template.tags,
        "agent_count": len(template.agents),
        "agents": [
            {
                "archetype": slot.archetype,
                "suggested_name": slot.suggested_name,
                "default_provider": slot.default_provider,
                "default_model": slot.default_model,
                "reports_to_index": slot.reports_to_index,
                "title_override": slot.title_override,
            }
            for slot in template.agents
        ],
    }
