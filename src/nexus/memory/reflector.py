"""Memory Reflector - auto-condenses oversized memory files.

Ported from munder-difflin/src/main/reflect.ts. Provides auto-condensation
of oversized memory files with a 3-region structure (pinned, condensed, recent),
a verify-dont-trust gate, and threshold detection.

The three regions are:
  1. Pinned durable facts (never condensed)
  2. One rolling recursive summary (condensed history)
  3. The newest K verbatim sections (recent)

Safety is layered so a bad LLM pass can never lose data: the verify gate
rejects any rewrite that fails structural or content checks, leaving the
original file byte-for-byte untouched.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from nexus.memory.reflector_types import (
    ParsedMemory,
    ReflectResult,
    ReflectSettings,
    Section,
)

# ── Constants ────────────────────────────────────────────────────────────────

BUDGET_BYTES: int = 131_072
"""Total memory.md budget (128 KB)."""

PINNED_HEADING: str = "## \U0001f4cc Durable facts (pinned - never condensed)"
"""Fixed heading for the pinned region."""

CONDENSED_HEADING: str = "## \U0001f5dc Condensed history"
"""Fixed heading for the condensed region."""

RECENT_HEADING: str = "## Recent"
"""Fixed heading for the recent region divider."""

CONDENSE_PROMPT: str = """\
You are a memory condensation assistant. Summarize the following evicted \
memory sections into a concise paragraph. You MUST preserve:
- Decisions (any line containing 'decided', 'decision', or 'chose')
- File paths (e.g. src/..., *.py, any slash-separated path)
- Commit SHAs (7+ hex character strings)
- Numeric results (dollar amounts with $, percentages with %)

Return ONLY a JSON object with exactly these keys:
{{
  "condensed": "<single paragraph summary preserving the above>",
  "hoist_lines": ["<lines that should be pinned as durable facts>"]
}}

Current condensed context (if any):
{condensed_context}

Evicted sections to summarize:
{evicted_text}
"""
"""Prompt template for LLM-based memory condensation."""


# ── Verify result type ───────────────────────────────────────────────────────


@dataclass
class VerifyResult:
    """Result of the verify-dont-trust gate.

    Attributes:
        ok: Whether all checks passed.
        reason: Why the check failed, or empty string on success.
    """

    ok: bool
    reason: str = ""


# ── Summarizer protocol ──────────────────────────────────────────────────────


class Summarizer(Protocol):
    """Protocol for the injected summarizer callable.

    Takes the current condensed text, evicted sections, and pinned text.
    Returns a tuple of (new_condensed, hoist_lines).
    """

    def __call__(
        self,
        condensed_text: str | None,
        evicted: list[Section],
        pinned: str | None,
    ) -> tuple[str, list[str]]: ...


# ── Pure helper functions ────────────────────────────────────────────────────


def count_sections(text: str) -> int:
    """Count level-2 (`## `) headings in text.

    Only counts headings that start with `## ` at the beginning of a line.
    H1 (`# `) and deeper headings (`### `) are excluded.

    Args:
        text: The full text to scan.

    Returns:
        Number of level-2 headings found.
    """
    return len(re.findall(r"^## ", text, re.MULTILINE))


def parse_memory(text: str) -> ParsedMemory:
    """Split a memory.md into header and the three regions.

    A legacy flat file (no pinned/condensed headings) parses with those
    fields as None and every `## ` section in `recent`. The structured
    blocks are created on first condense.

    Args:
        text: The full memory file text.

    Returns:
        A ParsedMemory with header, pinned, condensed, and recent sections.
    """
    lines = text.split("\n")

    # Find the first level-2 heading
    first_section = -1
    for i, line in enumerate(lines):
        if re.match(r"^## ", line):
            first_section = i
            break

    if first_section == -1:
        first_section = len(lines)

    header = "\n".join(lines[:first_section]).rstrip()

    # Carve the remaining lines into `## ` sections (heading + body until next `##`)
    sections: list[Section] = []
    cur: Section | None = None
    for i in range(first_section, len(lines)):
        line = lines[i]
        if re.match(r"^## ", line):
            if cur is not None:
                sections.append(cur)
            cur = Section(heading=line, body="")
        elif cur is not None:
            cur = Section(
                heading=cur.heading,
                body=(cur.body + "\n" + line) if cur.body else line,
            )
    if cur is not None:
        sections.append(cur)

    pinned: str | None = None
    condensed: str | None = None
    recent: list[Section] = []

    for s in sections:
        h = s.heading.strip()
        if h.startswith("## \U0001f4cc"):
            pinned = s.body.rstrip()
        elif h.startswith("## \U0001f5dc"):
            condensed = s.body.rstrip()
        elif h == RECENT_HEADING:
            # Divider only - its siblings ARE the recent list
            pass
        else:
            recent.append(s)

    return ParsedMemory(header=header, pinned=pinned, condensed=condensed, recent=recent)


def pinned_lines(pinned: str | None) -> list[str]:
    """Extract non-empty, trimmed lines from the pinned block.

    These are the lines we must never lose during condensation.

    Args:
        pinned: The pinned block body text, or None.

    Returns:
        List of non-empty trimmed lines.
    """
    if not pinned:
        return []
    return [line.strip() for line in pinned.split("\n") if line.strip()]


def merge_pinned(old_lines: list[str], hoist: list[str]) -> list[str]:
    """Append hoisted durable facts to the pinned set, skipping duplicates.

    Args:
        old_lines: Existing pinned lines.
        hoist: New lines to hoist into the pinned section.

    Returns:
        Merged list with new unique lines appended.
    """
    have = set(old_lines)
    out = list(old_lines)
    for raw in hoist:
        line = (raw or "").strip()
        if line and line not in have:
            have.add(line)
            out.append(line)
    return out


def rebuild(
    header: str,
    pinned_list: list[str],
    condensed: str,
    keep_sections: list[Section],
) -> str:
    """Reassemble the canonical 3-region file.

    Args:
        header: The H1 header text (before any ## sections).
        pinned_list: Lines for the pinned region.
        condensed: The condensed summary text.
        keep_sections: Recent sections to preserve verbatim.

    Returns:
        The rebuilt memory file as a single string.
    """
    parts: list[str] = []
    if header.strip():
        parts.append(header.strip())
    parts.append(PINNED_HEADING)
    parts.append("\n".join(pinned_list) if pinned_list else "_(none yet)_")
    parts.append(CONDENSED_HEADING)
    parts.append(condensed.strip())
    parts.append(RECENT_HEADING)
    for s in keep_sections:
        section_text = f"{s.heading}\n{s.body}".rstrip()
        parts.append(section_text)
    return "\n\n".join(parts) + "\n"


def verify(
    rebuilt: str,
    new_bytes: int,
    old_bytes: int,
    old_pinned_lines: list[str],
    merged_pinned: list[str],
    condensed: str,
    keep: list[Section],
) -> VerifyResult:
    """The verify-dont-trust gate for condensed rewrites.

    The rewrite is rejected (original kept verbatim) unless ALL checks pass.
    Checks performed:
      1. Structure: rebuilt parses back into valid 3-region structure.
      2. Size floor: new_bytes > 200.
      3. Non-empty condensed section.
      4. Actually smaller: new_bytes < old_bytes * 0.95.
      5. Pinned preserved: every old pinned line survives.
      6. Recent integrity: kept sections round-trip byte-for-byte.

    Args:
        rebuilt: The rebuilt file text.
        new_bytes: Size of the rebuilt file.
        old_bytes: Size of the original file.
        old_pinned_lines: Original pinned lines that must be preserved.
        merged_pinned: Expected merged pinned lines.
        condensed: The condensed summary text.
        keep: The sections that should be preserved verbatim.

    Returns:
        VerifyResult with ok=True on success, or ok=False with a reason.
    """
    # 1) Parses back into the 3-region structure
    parsed = parse_memory(rebuilt)
    if parsed.pinned is None or parsed.condensed is None:
        return VerifyResult(ok=False, reason="structure-missing-region")

    # 2) Non-empty and sane minimum size
    if new_bytes <= 200:
        return VerifyResult(ok=False, reason="too-small")

    # 3) Condensed must be non-empty
    if not condensed.strip():
        return VerifyResult(ok=False, reason="empty-condensed")

    # 4) Actually smaller (a no-op condense is a failure)
    if not (new_bytes < old_bytes * 0.95):
        return VerifyResult(ok=False, reason="not-smaller")

    # 5) Pinned preserved: every old pinned line survives
    new_pinned_set = set(pinned_lines(parsed.pinned))
    for line in old_pinned_lines:
        if line not in new_pinned_set:
            return VerifyResult(ok=False, reason="pinned-line-dropped")
    for line in merged_pinned:
        if line not in new_pinned_set:
            return VerifyResult(ok=False, reason="pinned-line-dropped")

    # 6) Recent integrity: kept sections round-trip byte-for-byte
    if len(parsed.recent) != len(keep):
        return VerifyResult(ok=False, reason="recent-section-altered")
    for i in range(len(keep)):
        a = f"{keep[i].heading}\n{keep[i].body}".rstrip()
        b = f"{parsed.recent[i].heading}\n{parsed.recent[i].body}".rstrip()
        if a != b:
            return VerifyResult(ok=False, reason="recent-section-altered")

    return VerifyResult(ok=True)


# ── MemoryReflector class ────────────────────────────────────────────────────


class MemoryReflector:
    """Auto-condenses oversized memory files using a 3-region structure.

    The reflector holds settings, exposes threshold checking via
    should_condense(), and runs the full pipeline via condense(). The
    summarizer is injected as a callable so the LLM call can be stubbed
    in tests.

    Optionally accepts an ``llm_callable`` for built-in LLM-powered
    summarization (same pattern as LLMFactExtractor). When provided,
    ``make_summarizer()`` returns a callable that delegates to the LLM;
    otherwise a heuristic fallback is used.

    Attributes:
        settings: The ReflectSettings controlling thresholds and behavior.
    """

    def __init__(
        self,
        settings: ReflectSettings | None = None,
        llm_callable: Callable[[str], Awaitable[str]] | None = None,
    ) -> None:
        """Initialize the MemoryReflector.

        Args:
            settings: Configuration for thresholds and behavior.
                Uses defaults if not specified.
            llm_callable: Optional async function that takes a prompt string
                and returns a response string. When provided, enables
                LLM-powered summarization via make_summarizer().
        """
        self.settings = settings or ReflectSettings()
        self._llm_callable = llm_callable
        self._executor: "concurrent.futures.ThreadPoolExecutor | None" = None

    def should_condense(self, file_bytes: int, section_count: int) -> bool:
        """Check whether a memory file should be condensed.

        The dual trigger: bytes > pct% of budget, OR many-section sprawl
        above the byte floor. The min_bytes floor gates BOTH paths to
        prevent wasting an LLM call on a tiny file.

        Args:
            file_bytes: Current file size in bytes.
            section_count: Number of level-2 sections in the file.

        Returns:
            True if the file should be condensed based on thresholds.
        """
        if file_bytes < self.settings.min_bytes:
            return False
        if file_bytes > (BUDGET_BYTES * self.settings.byte_trigger_pct) / 100:
            return True
        return section_count > self.settings.section_trigger

    def condense(
        self,
        agent_id: str,
        text: str,
        summarizer: Callable[
            [str | None, list[Section], str | None], tuple[str, list[str]]
        ],
    ) -> ReflectResult:
        """Run the full condensation pipeline.

        Steps:
          1. Parse the memory file into regions.
          2. Split recent into keep (newest K) and evict (older).
          3. Call summarizer for evicted sections.
          4. Rebuild the 3-region file.
          5. Verify the result passes all checks.

        Args:
            agent_id: The agent identifier.
            text: The full memory file text.
            summarizer: Callable that takes (condensed_text, evicted_sections,
                pinned_text) and returns (new_condensed, hoist_lines).

        Returns:
            ReflectResult indicating whether condensation succeeded.
        """
        old_bytes = len(text.encode("utf-8"))
        parsed = parse_memory(text)

        # Split recent into KEEP (newest K, verbatim) and EVICT (older)
        keep_count = max(1, self.settings.recent_keep)
        keep = parsed.recent[-keep_count:]
        evict = parsed.recent[: max(0, len(parsed.recent) - keep_count)]

        if not evict:
            return ReflectResult(
                id=agent_id,
                condensed=False,
                reason="nothing-to-evict",
                old_bytes=old_bytes,
            )

        # Call the summarizer
        new_condensed, hoist = summarizer(parsed.condensed, evict, parsed.pinned)

        # Rebuild into the 3-region shape
        old_pinned = pinned_lines(parsed.pinned)
        merged = merge_pinned(old_pinned, hoist)
        rebuilt = rebuild(parsed.header, merged, new_condensed, keep)
        new_bytes = len(rebuilt.encode("utf-8"))

        # Verify-dont-trust gate
        verdict = verify(
            rebuilt=rebuilt,
            new_bytes=new_bytes,
            old_bytes=old_bytes,
            old_pinned_lines=old_pinned,
            merged_pinned=merged,
            condensed=new_condensed,
            keep=keep,
        )

        if not verdict.ok:
            return ReflectResult(
                id=agent_id,
                condensed=False,
                reason=verdict.reason,
                old_bytes=old_bytes,
                new_bytes=new_bytes,
            )

        return ReflectResult(
            id=agent_id,
            condensed=True,
            reason="condensed",
            old_bytes=old_bytes,
            new_bytes=new_bytes,
            rebuilt_text=rebuilt,
        )

    async def _summarize_evicted(
        self,
        condensed_text: str | None,
        evicted: list[Section],
        pinned: str | None,
    ) -> tuple[str, list[str]]:
        """Summarize evicted sections using LLM or heuristic fallback.

        When ``self._llm_callable`` is set, builds a structured prompt
        from CONDENSE_PROMPT, calls the LLM, and parses the JSON response.
        Otherwise falls back to the heuristic (first 2 sentences per section).

        Args:
            condensed_text: Existing condensed summary, or None.
            evicted: List of sections being evicted from recent.
            pinned: Current pinned text, or None.

        Returns:
            Tuple of (new_condensed_text, hoist_lines).
        """
        if self._llm_callable is None:
            return self._heuristic_fallback(condensed_text, evicted)

        # Build evicted text block
        evicted_text = "\n\n".join(
            f"{s.heading}\n{s.body}" for s in evicted
        )
        prompt = CONDENSE_PROMPT.format(
            condensed_context=condensed_text or "(none)",
            evicted_text=evicted_text,
        )

        try:
            response = await self._llm_callable(prompt)
            data = json.loads(response)
            new_condensed = data.get("condensed", "")
            hoist_lines = data.get("hoist_lines", [])
            if not isinstance(new_condensed, str):
                new_condensed = str(new_condensed)
            if not isinstance(hoist_lines, list):
                hoist_lines = []
            hoist_lines = [
                str(line) for line in hoist_lines if line
            ]
            return (new_condensed, hoist_lines)
        except Exception:
            return self._heuristic_fallback(condensed_text, evicted)

    def _heuristic_fallback(
        self,
        condensed_text: str | None,
        evicted: list[Section],
    ) -> tuple[str, list[str]]:
        """Heuristic summarization fallback when no LLM is available.

        Takes the first 2 sentences of each evicted section body,
        joins them with newlines, and prepends existing condensed text.
        Uses _extract_durable_facts to provide hoist_lines containing
        decisions, file paths, commit SHAs, and critical numbers.

        Args:
            condensed_text: Existing condensed summary, or None.
            evicted: List of sections being evicted.

        Returns:
            Tuple of (new_condensed_text, hoist_lines_from_durable_facts).
        """
        parts: list[str] = []
        if condensed_text:
            parts.append(condensed_text)
        for section in evicted:
            sentences = section.body.split(". ")
            truncated = ". ".join(sentences[:2])
            if truncated and not truncated.endswith("."):
                truncated += "."
            parts.append(truncated)
        hoist_lines = self._extract_durable_facts(evicted)
        return ("\n".join(parts), hoist_lines)

    def _extract_durable_facts(self, evicted: list[Section]) -> list[str]:
        """Scan evicted sections for lines containing durable facts.

        Identifies lines with:
        - Decision keywords: 'decided', 'decision', 'chose'
        - File paths: patterns like ``src/...``, ``/*.``, ``*.py``
        - Commit SHAs: 7+ consecutive hex characters
        - Critical numbers: dollar amounts (``$``), percentages (``%``)

        Args:
            evicted: List of evicted sections to scan.

        Returns:
            List of matching lines (candidates for hoisting).
        """
        decision_re = re.compile(
            r"\b(decided|decision|chose)\b", re.IGNORECASE
        )
        file_path_re = re.compile(
            r"(src/[\w/.\-]+|/[\w/.\-]+\.\w+|\*\.\w+)"
        )
        commit_sha_re = re.compile(r"\b[0-9a-f]{8,40}\b")
        number_re = re.compile(r"(\$[\d,.]+|\d+%)")

        results: list[str] = []
        seen: set[str] = set()

        for section in evicted:
            for line in section.body.split("\n"):
                stripped = line.strip()
                if not stripped or stripped in seen:
                    continue
                if (
                    decision_re.search(stripped)
                    or file_path_re.search(stripped)
                    or commit_sha_re.search(stripped)
                    or number_re.search(stripped)
                ):
                    seen.add(stripped)
                    results.append(stripped)
        return results

    def make_summarizer(
        self,
    ) -> Callable[
        [str | None, list[Section], str | None], tuple[str, list[str]]
    ]:
        """Create a summarizer callable for use with condense().

        Returns a synchronous wrapper compatible with the Summarizer
        protocol. When ``llm_callable`` is available, uses asyncio to
        call ``_summarize_evicted``. Otherwise calls the heuristic
        fallback directly.

        Returns:
            A callable matching the Summarizer protocol signature.
        """
        if self._llm_callable is None:

            def _sync_summarizer(
                condensed_text: str | None,
                evicted: list[Section],
                pinned: str | None,
            ) -> tuple[str, list[str]]:
                return self._heuristic_fallback(condensed_text, evicted)

            return _sync_summarizer

        def _llm_summarizer(
            condensed_text: str | None,
            evicted: list[Section],
            pinned: str | None,
        ) -> tuple[str, list[str]]:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                if self._executor is None:
                    self._executor = concurrent.futures.ThreadPoolExecutor(1)
                future = self._executor.submit(
                    asyncio.run,
                    self._summarize_evicted(
                        condensed_text, evicted, pinned
                    ),
                )
                return future.result()
            else:
                return asyncio.run(
                    self._summarize_evicted(
                        condensed_text, evicted, pinned
                    )
                )

        return _llm_summarizer
