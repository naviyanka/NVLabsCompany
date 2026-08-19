"""Template registry for loading and managing agent role templates.

Provides AgentTemplate dataclass for representing parsed templates and
TemplateRegistry class for discovering, loading, and querying templates
from a directory of Markdown files with YAML frontmatter.
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class AgentTemplate:
    """Represents a parsed agent role template.

    Attributes:
        name: Display name of the agent role (from YAML frontmatter).
        description: Brief description of the role (from YAML frontmatter).
        body: The Markdown body content after the frontmatter.
        file_path: Absolute path to the source template file.
    """

    name: str
    description: str
    body: str
    file_path: str


def _parse_template(file_path: Path) -> AgentTemplate:
    """Parse a Markdown template file with YAML frontmatter.

    Expects files in the format:
        ---
        name: Template Name
        description: Template description.
        ---

        # Markdown body content...

    Args:
        file_path: Path to the Markdown template file.

    Returns:
        Parsed AgentTemplate instance.

    Raises:
        ValueError: If the file does not contain valid YAML frontmatter.
    """
    content = file_path.read_text(encoding="utf-8")

    if not content.startswith("---"):
        raise ValueError(
            f"Template file {file_path} does not start with YAML frontmatter delimiter '---'"
        )

    # Find the closing --- delimiter (second occurrence)
    second_delimiter = content.index("---", 3)
    frontmatter_text = content[3:second_delimiter].strip()
    body = content[second_delimiter + 3:].strip()

    frontmatter = yaml.safe_load(frontmatter_text)
    if not isinstance(frontmatter, dict):
        raise ValueError(f"Template file {file_path} has invalid YAML frontmatter")

    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")

    return AgentTemplate(
        name=name,
        description=description,
        body=body,
        file_path=str(file_path),
    )


class TemplateRegistry:
    """Registry for discovering and managing agent role templates.

    Loads Markdown template files from a directory, parses YAML frontmatter
    for metadata, and provides lookup by template name.

    Example:
        >>> registry = TemplateRegistry()
        >>> registry.load_from_directory(Path("src/nexus/templates/agents"))
        >>> templates = registry.list_templates()
        >>> architect = registry.get_template("Software Architect")
    """

    def __init__(self) -> None:
        """Initialize an empty template registry."""
        self._templates: dict[str, AgentTemplate] = {}
        self._directory: Path | None = None

    def load_from_directory(self, path: Path) -> None:
        """Load all Markdown template files from the specified directory.

        Discovers all .md files in the directory (non-recursive), parses
        their YAML frontmatter and body content, and registers them by name.

        Args:
            path: Directory path containing .md template files.

        Raises:
            FileNotFoundError: If the directory does not exist.
        """
        if not path.exists():
            raise FileNotFoundError(f"Template directory not found: {path}")

        self._directory = path
        self._templates.clear()

        for md_file in sorted(path.glob("*.md")):
            template = _parse_template(md_file)
            self._templates[template.name] = template

    def list_templates(self) -> list[AgentTemplate]:
        """Return all loaded templates as a list.

        Returns:
            List of all AgentTemplate instances, sorted by name.
        """
        return sorted(self._templates.values(), key=lambda t: t.name)

    def get_template(self, name: str) -> AgentTemplate | None:
        """Retrieve a template by its name.

        Args:
            name: The exact template name as defined in YAML frontmatter.

        Returns:
            The matching AgentTemplate, or None if not found.
        """
        return self._templates.get(name)

    def reload(self) -> None:
        """Reload templates from the previously loaded directory.

        Re-reads all template files, picking up any changes made since
        the last load. Has no effect if load_from_directory has not been
        called yet.
        """
        if self._directory is not None:
            self.load_from_directory(self._directory)
