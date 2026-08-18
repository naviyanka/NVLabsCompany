"""NEXUS Agent Identity System - personality, memory, and context management.

This module provides the identity layer for NEXUS agents:
- Soul: Core personality definition (traits, style, expertise, values)
- SoulTemplate: Pre-built soul templates for common agent roles
- Persona: Memory namespace and context assembly per agent
- WorkingContext: Assembled context ready for model consumption
- ContextBudget: Token allocation strategy across identity/memory/task
"""

from nexus.identity.persona import ContextBudget, Persona, WorkingContext
from nexus.identity.soul import Soul, SoulTemplate, system_prompt_from_soul

# Re-export SOUL_TEMPLATES for convenience
from nexus.identity.soul import SOUL_TEMPLATES

__all__ = [
    "Soul",
    "SoulTemplate",
    "SOUL_TEMPLATES",
    "system_prompt_from_soul",
    "Persona",
    "WorkingContext",
    "ContextBudget",
]
