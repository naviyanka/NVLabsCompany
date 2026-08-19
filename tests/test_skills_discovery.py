"""Tests for the skills discovery module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from nexus.tools.skills_discovery import (
    LocalSkill,
    list_local_skills,
    parse_skill_frontmatter,
    scan_skill_dir,
)


class TestParseSkillFrontmatter:
    """Tests for parse_skill_frontmatter function."""

    def test_inline_name_and_description(self) -> None:
        """Parse standard inline name and description values."""
        md = "---\nname: My Skill\ndescription: A useful skill\n---\n# Content"
        result = parse_skill_frontmatter(md)
        assert result == {"name": "My Skill", "description": "A useful skill"}

    def test_block_scalar_pipe(self) -> None:
        """Parse block scalar description with | indicator."""
        md = (
            "---\n"
            "name: Block Skill\n"
            "description: |\n"
            "  This is a multiline\n"
            "  description here\n"
            "---\n"
        )
        result = parse_skill_frontmatter(md)
        assert result["name"] == "Block Skill"
        assert result["description"] == "This is a multiline description here"

    def test_block_scalar_folded(self) -> None:
        """Parse block scalar description with > (folded) indicator."""
        md = (
            "---\n"
            "name: Folded Skill\n"
            "description: >\n"
            "  First line\n"
            "  Second line\n"
            "---\n"
        )
        result = parse_skill_frontmatter(md)
        assert result["name"] == "Folded Skill"
        assert result["description"] == "First line Second line"

    def test_quoted_values(self) -> None:
        """Parse quoted name and description values."""
        md = '---\nname: "Quoted Skill"\ndescription: \'A quoted desc\'\n---\n'
        result = parse_skill_frontmatter(md)
        assert result["name"] == "Quoted Skill"
        assert result["description"] == "A quoted desc"

    def test_missing_frontmatter(self) -> None:
        """Return empty dict when no frontmatter present."""
        md = "# Just a heading\nSome content"
        result = parse_skill_frontmatter(md)
        assert result == {}

    def test_name_only(self) -> None:
        """Return only name when description is absent."""
        md = "---\nname: Solo Name\n---\n"
        result = parse_skill_frontmatter(md)
        assert result == {"name": "Solo Name"}

    def test_empty_frontmatter(self) -> None:
        """Return empty dict for frontmatter without relevant keys."""
        md = "---\nauthor: Someone\nversion: 1.0\n---\n"
        result = parse_skill_frontmatter(md)
        assert result == {}


class TestScanSkillDir:
    """Tests for scan_skill_dir function."""

    def test_scan_finds_skills(self, tmp_path: Path) -> None:
        """Discover skill folders containing SKILL.md."""
        skill_dir = tmp_path / "alpha"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: Alpha\ndescription: First skill\n---\n"
        )

        skills = scan_skill_dir(str(tmp_path), "claude", "user")
        assert len(skills) == 1
        assert skills[0].name == "Alpha"
        assert skills[0].description == "First skill"
        assert skills[0].id == "user:alpha"
        assert skills[0].provider == "claude"
        assert skills[0].scope == "user"

    def test_scan_uses_folder_name_as_fallback(self, tmp_path: Path) -> None:
        """Use folder name when frontmatter has no name."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\nauthor: test\n---\n")

        skills = scan_skill_dir(str(tmp_path), "opencode", "project")
        assert len(skills) == 1
        assert skills[0].name == "my-skill"
        assert skills[0].description == ""

    def test_scan_ignores_dirs_without_skill_md(self, tmp_path: Path) -> None:
        """Skip directories that do not contain SKILL.md."""
        (tmp_path / "no-skill").mkdir()
        (tmp_path / "no-skill" / "README.md").write_text("# Readme")

        skills = scan_skill_dir(str(tmp_path), "claude", "user")
        assert skills == []

    def test_scan_nonexistent_directory(self) -> None:
        """Return empty list for non-existent directory."""
        skills = scan_skill_dir("/nonexistent/path", "claude", "user")
        assert skills == []

    def test_scan_multiple_skills(self, tmp_path: Path) -> None:
        """Discover multiple skill folders."""
        for name in ("beta", "gamma"):
            d = tmp_path / name
            d.mkdir()
            (d / "SKILL.md").write_text(
                f"---\nname: {name.title()}\ndescription: Skill {name}\n---\n"
            )

        skills = scan_skill_dir(str(tmp_path), "codex", "bundled")
        assert len(skills) == 2
        names = [s.name for s in skills]
        assert "Beta" in names
        assert "Gamma" in names


class TestListLocalSkills:
    """Tests for list_local_skills function."""

    def test_deduplication_scope_precedence(self, tmp_path: Path) -> None:
        """Project scope takes precedence over user scope."""
        # Set up user-level skill
        user_dir = tmp_path / "user" / ".claude" / "skills" / "my-skill"
        user_dir.mkdir(parents=True)
        (user_dir / "SKILL.md").write_text(
            "---\nname: MySkill\ndescription: User version\n---\n"
        )

        # Set up project-level skill with same name
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        proj_skill = project_dir / ".claude" / "skills" / "my-skill"
        proj_skill.mkdir(parents=True)
        (proj_skill / "SKILL.md").write_text(
            "---\nname: MySkill\ndescription: Project version\n---\n"
        )

        with patch.object(Path, "home", return_value=tmp_path / "user"):
            skills = list_local_skills(cwds=[str(project_dir)])

        # Should keep project version (higher precedence)
        matching = [s for s in skills if s.name == "MySkill"]
        assert len(matching) == 1
        assert matching[0].scope == "project"
        assert matching[0].description == "Project version"

    def test_bundled_dir_scanned(self, tmp_path: Path) -> None:
        """Bundled directory skills are discovered."""
        bundled = tmp_path / "bundled" / "helper"
        bundled.mkdir(parents=True)
        (bundled / "SKILL.md").write_text(
            "---\nname: Helper\ndescription: Bundled helper\n---\n"
        )

        with patch.object(Path, "home", return_value=tmp_path / "empty"):
            skills = list_local_skills(bundled_dir=str(tmp_path / "bundled"))

        assert len(skills) == 1
        assert skills[0].name == "Helper"
        assert skills[0].scope == "bundled"

    def test_results_sorted_by_name(self, tmp_path: Path) -> None:
        """Results are sorted alphabetically by name."""
        user_claude = tmp_path / "home" / ".claude" / "skills"
        for name in ("zebra", "alpha", "middle"):
            d = user_claude / name
            d.mkdir(parents=True, exist_ok=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n")

        with patch.object(Path, "home", return_value=tmp_path / "home"):
            skills = list_local_skills()

        names = [s.name for s in skills]
        assert names == sorted(names, key=str.lower)

    def test_missing_directories_handled(self, tmp_path: Path) -> None:
        """Non-existent directories are handled gracefully."""
        with patch.object(Path, "home", return_value=tmp_path / "nowhere"):
            skills = list_local_skills(cwds=["/nonexistent/project"])

        assert skills == []

    def test_user_over_bundled_precedence(self, tmp_path: Path) -> None:
        """User scope takes precedence over bundled scope."""
        # Bundled
        bundled = tmp_path / "bundled" / "tool"
        bundled.mkdir(parents=True)
        (bundled / "SKILL.md").write_text(
            "---\nname: Tool\ndescription: Bundled\n---\n"
        )

        # User
        user_dir = tmp_path / "home" / ".claude" / "skills" / "tool"
        user_dir.mkdir(parents=True)
        (user_dir / "SKILL.md").write_text(
            "---\nname: Tool\ndescription: User\n---\n"
        )

        with patch.object(Path, "home", return_value=tmp_path / "home"):
            skills = list_local_skills(
                bundled_dir=str(tmp_path / "bundled")
            )

        matching = [s for s in skills if s.name == "Tool"]
        assert len(matching) == 1
        assert matching[0].scope == "user"
        assert matching[0].description == "User"
