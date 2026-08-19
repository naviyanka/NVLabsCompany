"""Agent template system for NEXUS.

Provides a registry-based system for loading and managing agent role templates
defined as Markdown files with YAML frontmatter.
"""

from nexus.templates.registry import AgentTemplate, TemplateRegistry

__all__ = ["AgentTemplate", "TemplateRegistry"]
