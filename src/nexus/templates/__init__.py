"""Agent template system for NEXUS.

Provides a registry-based system for loading and managing agent role templates
defined as Markdown files with YAML frontmatter, and hire manifests for portable
agent role templates in JSON format.
"""

from nexus.templates.hire_manifest import (
    HIRE_SPEC_V1,
    SAFE_FLAG_NAMES,
    HireManifest,
    HireValidation,
    validate_hire_manifest,
)
from nexus.templates.hire_registry import ManifestRegistry
from nexus.templates.registry import AgentTemplate, TemplateRegistry

__all__ = [
    "AgentTemplate",
    "HIRE_SPEC_V1",
    "HireManifest",
    "HireValidation",
    "ManifestRegistry",
    "SAFE_FLAG_NAMES",
    "TemplateRegistry",
    "validate_hire_manifest",
]
