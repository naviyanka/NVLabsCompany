"""Tool Catalog - discoverable prerequisite and engine tools with setup probing.

Provides a structured catalog of CLI tools that the Nexus ecosystem depends on,
including prerequisite utilities (uv, git), memory tools (mempalace), and agent
engine entries dynamically derived from the provider presets registry.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum


class ToolKind(str, Enum):
    """Classification of tool purpose within the ecosystem."""

    prerequisite = "prerequisite"
    memory = "memory"
    engine = "engine"


@dataclass(frozen=True)
class ToolSpec:
    """Immutable descriptor for a cataloged tool.

    Attributes:
        id: Unique tool identifier.
        bin: Binary name to probe on PATH (None if not directly executable).
        label: Human-readable display name.
        kind: Category of tool.
        why: Short explanation of why the tool is needed.
        essential: Whether the tool is required for core operation.
        install_posix: Installation command for POSIX systems.
        install_win32: Installation command for Windows systems.
        docs_url: Optional URL to documentation.
    """

    id: str
    bin: str | None
    label: str
    kind: ToolKind
    why: str
    essential: bool
    install_posix: str
    install_win32: str
    docs_url: str | None = None


BASE_TOOLS: list[ToolSpec] = [
    ToolSpec(
        id="uv",
        bin="uv",
        label="uv",
        kind=ToolKind.prerequisite,
        why="Fast Python package manager and tool runner.",
        essential=True,
        install_posix="curl -LsSf https://astral.sh/uv/install.sh | sh",
        install_win32=(
            'powershell -ExecutionPolicy ByPass -c'
            ' "irm https://astral.sh/uv/install.ps1 | iex"'
        ),
        docs_url="https://docs.astral.sh/uv/",
    ),
    ToolSpec(
        id="mempalace",
        bin=None,
        label="mempalace",
        kind=ToolKind.memory,
        why="Persistent memory layer for agent context.",
        essential=True,
        install_posix="uv tool install mempalace",
        install_win32="uv tool install mempalace",
    ),
    ToolSpec(
        id="git",
        bin="git",
        label="git",
        kind=ToolKind.prerequisite,
        why="Version control for source code.",
        essential=True,
        install_posix="xcode-select --install",
        install_win32="winget install --id Git.Git -e",
        docs_url="https://git-scm.com/downloads",
    ),
    ToolSpec(
        id="node",
        bin="node",
        label="node",
        kind=ToolKind.prerequisite,
        why="JavaScript runtime for agent CLI tools.",
        essential=False,
        install_posix="",
        install_win32="",
        docs_url="https://nodejs.org",
    ),
]


def tool_catalog() -> list[ToolSpec]:
    """Return the full tool catalog including engine entries from provider presets.

    Combines BASE_TOOLS with dynamically-generated engine entries for each
    non-custom provider preset that has a default_command defined.

    Returns:
        Complete list of ToolSpec entries.
    """
    from nexus.adapters.provider_presets import (
        AgentProviderID,
        PROVIDER_PRESETS,
    )

    engine_tools: list[ToolSpec] = []
    for preset in PROVIDER_PRESETS.values():
        if preset.id == AgentProviderID.custom:
            continue
        if not preset.default_command:
            continue
        engine_tools.append(
            ToolSpec(
                id=f"engine:{preset.id.value}",
                bin=preset.default_command,
                label=preset.label,
                kind=ToolKind.engine,
                why=f"Agent engine - {preset.default_command}.",
                essential=(preset.id == AgentProviderID.claude),
                install_posix=preset.install_command or "",
                install_win32=preset.install_command or "",
                docs_url=preset.docs_url,
            )
        )

    return list(BASE_TOOLS) + engine_tools


def probe_tool(bin_name: str) -> str | None:
    """Probe whether a binary is available on the system PATH.

    Args:
        bin_name: Name of the binary to search for.

    Returns:
        Absolute path to the binary if found, None otherwise.
    """
    return shutil.which(bin_name)


def get_setup_status() -> list[dict]:
    """Return catalog entries annotated with their availability on the current system.

    Each entry includes all ToolSpec fields plus 'found' (bool) and 'path' (str | None).

    Returns:
        List of dicts with tool info and availability status.
    """
    results: list[dict] = []
    for tool in tool_catalog():
        path: str | None = None
        found = False
        if tool.bin is not None:
            path = probe_tool(tool.bin)
            found = path is not None
        results.append({
            "id": tool.id,
            "bin": tool.bin,
            "label": tool.label,
            "kind": tool.kind.value,
            "why": tool.why,
            "essential": tool.essential,
            "install_posix": tool.install_posix,
            "install_win32": tool.install_win32,
            "docs_url": tool.docs_url,
            "found": found,
            "path": path,
        })
    return results
