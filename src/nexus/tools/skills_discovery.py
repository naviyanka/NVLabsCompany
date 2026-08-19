"""Local skills discovery: scan filesystem for skill definitions.

Discovers skills from multiple providers (Claude, OpenCode, Codex) by
walking known directory structures. Parses YAML frontmatter from SKILL.md
files and deduplicates by (provider, name) with scope precedence.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LocalSkill:
    """A locally discovered skill definition.

    Attributes:
        id: Unique identifier in format '{scope}:{folder_name}'.
        name: Human-readable skill name (from frontmatter or folder name).
        description: Skill description (from frontmatter or empty).
        provider: Tool provider ('claude', 'opencode', or 'codex').
        scope: Discovery scope ('user', 'project', or 'bundled').
        path: Filesystem path to the skill directory.
    """

    id: str
    name: str
    description: str
    provider: str
    scope: str
    path: str


_SCOPE_PRECEDENCE: dict[str, int] = {
    "bundled": 1,
    "user": 2,
    "project": 3,
}


def parse_skill_frontmatter(md: str) -> dict[str, str]:
    """Extract name and description from YAML frontmatter in a SKILL.md file.

    Handles standard inline values, quoted values, and block scalar indicators
    (| and >) for multiline descriptions.

    Args:
        md: Raw markdown content of a SKILL.md file.

    Returns:
        Dictionary with optional 'name' and 'description' keys extracted
        from frontmatter.
    """
    # Match frontmatter between --- delimiters
    match = re.match(r"^---\s*\n(.*?)\n---", md, re.DOTALL)
    if not match:
        return {}

    frontmatter = match.group(1)
    lines = frontmatter.split("\n")
    result: dict[str, str] = {}

    i = 0
    while i < len(lines):
        line = lines[i]
        # Match key: value patterns
        key_match = re.match(r"^(name|description)\s*:\s*(.*)", line)
        if key_match:
            key = key_match.group(1)
            value = key_match.group(2).strip()

            if value in ("|", ">"):
                # Block scalar: collect indented lines
                block_lines: list[str] = []
                i += 1
                while i < len(lines):
                    if lines[i] and not lines[i][0].isspace():
                        break
                    if lines[i].strip():
                        block_lines.append(lines[i].strip())
                    i += 1
                result[key] = " ".join(block_lines)
                continue
            else:
                # Strip surrounding quotes
                if (
                    len(value) >= 2
                    and value[0] in ('"', "'")
                    and value[-1] == value[0]
                ):
                    value = value[1:-1]
                if value:
                    result[key] = value
        i += 1

    return result


def scan_skill_dir(
    dir_path: str,
    provider: str,
    scope: str,
) -> list[LocalSkill]:
    """Walk a directory for folders containing SKILL.md and parse them.

    Each subdirectory containing a SKILL.md file is treated as a skill.
    The frontmatter is parsed to extract name and description.

    Args:
        dir_path: Root directory to scan for skill folders.
        provider: Provider name ('claude', 'opencode', or 'codex').
        scope: Discovery scope ('user', 'project', or 'bundled').

    Returns:
        List of LocalSkill instances found in the directory.
    """
    skills: list[LocalSkill] = []
    root = Path(dir_path)

    if not root.is_dir():
        return skills

    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        skill_md = entry / "SKILL.md"
        if not skill_md.is_file():
            continue

        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue

        meta = parse_skill_frontmatter(content)
        folder_name = entry.name
        skill = LocalSkill(
            id=f"{scope}:{folder_name}",
            name=meta.get("name", folder_name),
            description=meta.get("description", ""),
            provider=provider,
            scope=scope,
            path=str(entry),
        )
        skills.append(skill)

    return skills


def list_local_skills(
    cwds: list[str] | None = None,
    bundled_dir: str | None = None,
) -> list[LocalSkill]:
    """Discover all local skills from known provider directories.

    Scans bundled, user-level, and project-level skill directories for
    Claude, OpenCode, and Codex providers. Deduplicates by (provider,
    name.lower()) with scope precedence: project > user > bundled.

    Args:
        cwds: List of working directories to scan for project-level skills.
        bundled_dir: Optional path to bundled skills directory.

    Returns:
        Sorted list of deduplicated LocalSkill instances.
    """
    all_skills: list[LocalSkill] = []
    home = Path.home()

    # Bundled skills (lowest precedence)
    if bundled_dir:
        all_skills.extend(scan_skill_dir(bundled_dir, "claude", "bundled"))

    # User-level skills
    claude_user = str(home / ".claude" / "skills")
    all_skills.extend(scan_skill_dir(claude_user, "claude", "user"))

    opencode_user = str(home / ".config" / "opencode" / "plugin")
    all_skills.extend(scan_skill_dir(opencode_user, "opencode", "user"))

    codex_user = str(home / ".codex" / "plugins")
    all_skills.extend(scan_skill_dir(codex_user, "codex", "user"))

    # Project-level skills
    for cwd in cwds or []:
        claude_project = os.path.join(cwd, ".claude", "skills")
        all_skills.extend(scan_skill_dir(claude_project, "claude", "project"))

        opencode_project = os.path.join(cwd, ".opencode", "plugin")
        all_skills.extend(
            scan_skill_dir(opencode_project, "opencode", "project")
        )

    # Deduplicate by (provider, name.lower()) with scope precedence
    seen: dict[tuple[str, str], LocalSkill] = {}
    for skill in all_skills:
        key = (skill.provider, skill.name.lower())
        existing = seen.get(key)
        if existing is None:
            seen[key] = skill
        else:
            existing_prec = _SCOPE_PRECEDENCE.get(existing.scope, 0)
            new_prec = _SCOPE_PRECEDENCE.get(skill.scope, 0)
            if new_prec > existing_prec:
                seen[key] = skill

    # Sort by name
    return sorted(seen.values(), key=lambda s: s.name.lower())


__all__ = [
    "LocalSkill",
    "parse_skill_frontmatter",
    "scan_skill_dir",
    "list_local_skills",
]
