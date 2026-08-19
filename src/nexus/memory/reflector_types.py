"""Memory Reflector types - settings, result structures, and parsed memory regions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReflectSettings:
    """Configuration for the memory reflector auto-condense system.

    Attributes:
        enabled: Whether the reflector is active.
        interval_seconds: How often to scan for oversized memory files.
        byte_trigger_pct: Condense when bytes exceed this percent of BUDGET_BYTES.
        section_trigger: Condense when section count exceeds this (AND bytes > min_bytes).
        recent_keep: Newest K verbatim sections always kept untouched.
        min_bytes: Never condense a file smaller than this.
    """

    enabled: bool = True
    interval_seconds: int = 300
    byte_trigger_pct: int = 80
    section_trigger: int = 20
    recent_keep: int = 5
    min_bytes: int = 4096


@dataclass
class ReflectResult:
    """Outcome of one agent's reflect attempt.

    Attributes:
        id: The agent identifier.
        condensed: Whether the file was actually rewritten.
        reason: Why (skipped/aborted/done), for logging and UI.
        old_bytes: Original file size in bytes, or None.
        new_bytes: New file size in bytes after condensation, or None.
        rebuilt_text: The rebuilt memory file text on success, or None.
            Populated only when condensed=True so the caller can persist
            the result without re-running the summarizer.
    """

    id: str
    condensed: bool
    reason: str
    old_bytes: int | None = None
    new_bytes: int | None = None
    rebuilt_text: str | None = None


@dataclass
class Section:
    """A level-2 heading section: its heading line and the body text beneath it.

    Attributes:
        heading: The `## ` heading line.
        body: The body text beneath the heading (lines joined by newline).
    """

    heading: str
    body: str


@dataclass
class ParsedMemory:
    """A parsed memory.md split into the three regions.

    Pinned and condensed are None for legacy (unstructured) files; they
    are created on first condense.

    Attributes:
        header: The `# Memory` H1 + any preamble before the first `##`.
        pinned: Body under the pinned heading (no heading line), or None.
        condensed: Body under the condensed heading, or None.
        recent: Every other `## ` section, in file order (oldest to newest).
    """

    header: str
    pinned: str | None = None
    condensed: str | None = None
    recent: list[Section] = field(default_factory=list)
