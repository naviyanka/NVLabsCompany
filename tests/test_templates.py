"""Tests for the agent template registry system.

Covers template loading, YAML frontmatter parsing, name-based lookup,
listing all templates, handling unknown names, and reload functionality.
"""

from pathlib import Path

import pytest

from nexus.templates import AgentTemplate, TemplateRegistry


@pytest.fixture
def agents_dir() -> Path:
    """Return the path to the bundled agent templates directory."""
    return Path(__file__).parent.parent / "src" / "nexus" / "templates" / "agents"


@pytest.fixture
def registry(agents_dir: Path) -> TemplateRegistry:
    """Create a TemplateRegistry loaded with bundled agent templates."""
    reg = TemplateRegistry()
    reg.load_from_directory(agents_dir)
    return reg


@pytest.fixture
def tmp_templates(tmp_path: Path) -> Path:
    """Create a temporary directory with sample template files for testing."""
    template_a = tmp_path / "alpha.md"
    template_a.write_text(
        "---\n"
        "name: Alpha Agent\n"
        "description: First test agent.\n"
        "---\n\n"
        "# Alpha Agent\n\n"
        "Alpha body content.\n"
    )

    template_b = tmp_path / "beta.md"
    template_b.write_text(
        "---\n"
        "name: Beta Agent\n"
        "description: Second test agent.\n"
        "---\n\n"
        "# Beta Agent\n\n"
        "Beta body content.\n"
    )

    # Non-markdown file should be ignored
    (tmp_path / "readme.txt").write_text("This should be ignored.")

    return tmp_path


class TestTemplateRegistry:
    """Tests for TemplateRegistry loading and discovery."""

    def test_load_from_directory_discovers_all_md_files(
        self, registry: TemplateRegistry
    ) -> None:
        """Registry should discover all 10 bundled agent template files."""
        templates = registry.list_templates()
        assert len(templates) == 10

    def test_load_from_directory_ignores_non_md_files(
        self, tmp_templates: Path
    ) -> None:
        """Registry should only load .md files, ignoring other file types."""
        reg = TemplateRegistry()
        reg.load_from_directory(tmp_templates)
        templates = reg.list_templates()
        assert len(templates) == 2

    def test_load_from_nonexistent_directory_raises(self) -> None:
        """Registry should raise FileNotFoundError for missing directories."""
        reg = TemplateRegistry()
        with pytest.raises(FileNotFoundError):
            reg.load_from_directory(Path("/nonexistent/path"))


class TestFrontmatterParsing:
    """Tests for YAML frontmatter extraction from template files."""

    def test_parses_name_from_frontmatter(self, registry: TemplateRegistry) -> None:
        """Template name should be extracted from YAML frontmatter."""
        template = registry.get_template("Software Architect")
        assert template is not None
        assert template.name == "Software Architect"

    def test_parses_description_from_frontmatter(
        self, registry: TemplateRegistry
    ) -> None:
        """Template description should be extracted from YAML frontmatter."""
        template = registry.get_template("Software Architect")
        assert template is not None
        assert "System design" in template.description

    def test_body_contains_markdown_content(
        self, registry: TemplateRegistry
    ) -> None:
        """Template body should contain Markdown content after frontmatter."""
        template = registry.get_template("Software Architect")
        assert template is not None
        assert "# Software Architect" in template.body
        assert "## Rules" in template.body
        assert "## Process" in template.body

    def test_file_path_is_set(self, registry: TemplateRegistry) -> None:
        """Template file_path should reference the source file."""
        template = registry.get_template("Software Architect")
        assert template is not None
        assert template.file_path.endswith("software-architect.md")

    def test_parses_custom_template(self, tmp_templates: Path) -> None:
        """Registry should correctly parse custom template frontmatter."""
        reg = TemplateRegistry()
        reg.load_from_directory(tmp_templates)
        template = reg.get_template("Alpha Agent")
        assert template is not None
        assert template.name == "Alpha Agent"
        assert template.description == "First test agent."
        assert "Alpha body content." in template.body


class TestGetTemplate:
    """Tests for template retrieval by name."""

    def test_get_template_returns_correct_template(
        self, registry: TemplateRegistry
    ) -> None:
        """get_template should return the template matching the given name."""
        template = registry.get_template("Code Reviewer")
        assert template is not None
        assert template.name == "Code Reviewer"
        assert "code review" in template.description.lower()

    def test_get_template_returns_none_for_unknown_name(
        self, registry: TemplateRegistry
    ) -> None:
        """get_template should return None when no template matches the name."""
        template = registry.get_template("Nonexistent Agent")
        assert template is None

    def test_get_template_is_case_sensitive(
        self, registry: TemplateRegistry
    ) -> None:
        """get_template uses exact name matching (case-sensitive)."""
        template = registry.get_template("software architect")
        assert template is None


class TestListTemplates:
    """Tests for listing all loaded templates."""

    def test_list_templates_returns_all_loaded(
        self, registry: TemplateRegistry
    ) -> None:
        """list_templates should return all templates loaded from directory."""
        templates = registry.list_templates()
        assert len(templates) == 10
        names = {t.name for t in templates}
        assert "Software Architect" in names
        assert "Code Reviewer" in names
        assert "Backend Engineer" in names
        assert "QA Engineer" in names
        assert "DevOps Engineer" in names
        assert "Security Engineer" in names
        assert "Product Manager" in names
        assert "Data Engineer" in names
        assert "Frontend Engineer" in names
        assert "SRE" in names

    def test_list_templates_sorted_by_name(
        self, registry: TemplateRegistry
    ) -> None:
        """list_templates should return templates sorted alphabetically by name."""
        templates = registry.list_templates()
        names = [t.name for t in templates]
        assert names == sorted(names)

    def test_list_templates_returns_agent_template_instances(
        self, registry: TemplateRegistry
    ) -> None:
        """list_templates should return AgentTemplate dataclass instances."""
        templates = registry.list_templates()
        for template in templates:
            assert isinstance(template, AgentTemplate)


class TestReload:
    """Tests for the reload functionality."""

    def test_reload_picks_up_new_files(self, tmp_path: Path) -> None:
        """reload should discover new template files added after initial load."""
        # Create initial template
        (tmp_path / "first.md").write_text(
            "---\nname: First\ndescription: First agent.\n---\n\n# First\n\nBody.\n"
        )

        reg = TemplateRegistry()
        reg.load_from_directory(tmp_path)
        assert len(reg.list_templates()) == 1

        # Add a new template file
        (tmp_path / "second.md").write_text(
            "---\nname: Second\ndescription: Second agent.\n---\n\n# Second\n\nBody.\n"
        )

        reg.reload()
        assert len(reg.list_templates()) == 2
        assert reg.get_template("Second") is not None

    def test_reload_removes_deleted_files(self, tmp_path: Path) -> None:
        """reload should remove templates whose files no longer exist."""
        template_file = tmp_path / "temp.md"
        template_file.write_text(
            "---\nname: Temp\ndescription: Temporary.\n---\n\n# Temp\n\nBody.\n"
        )

        reg = TemplateRegistry()
        reg.load_from_directory(tmp_path)
        assert reg.get_template("Temp") is not None

        template_file.unlink()
        reg.reload()
        assert reg.get_template("Temp") is None

    def test_reload_without_prior_load_is_noop(self) -> None:
        """reload on a registry that never loaded should not raise."""
        reg = TemplateRegistry()
        reg.reload()  # Should not raise
        assert reg.list_templates() == []
