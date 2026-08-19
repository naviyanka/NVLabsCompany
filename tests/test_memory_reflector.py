"""Comprehensive tests for the Memory Reflector (auto-condense) module."""

from nexus.memory.reflector import (
    BUDGET_BYTES,
    CONDENSED_HEADING,
    PINNED_HEADING,
    RECENT_HEADING,
    MemoryReflector,
    count_sections,
    merge_pinned,
    parse_memory,
    pinned_lines,
    rebuild,
    verify,
)
from nexus.memory.reflector_types import ReflectSettings, Section

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_3region_file(
    header: str = "# Agent Memory",
    pinned_body: str = "- Always use UTC timestamps\n- Project root is /workspace",
    condensed_body: str = "Agent completed initial setup and configured CI pipeline.",
    recent_sections: list[tuple[str, str]] | None = None,
) -> str:
    """Build a valid 3-region memory file for testing."""
    if recent_sections is None:
        recent_sections = [
            ("## Task: deploy v2", "Deployed version 2 to staging."),
            ("## Task: fix auth bug", "Fixed the authentication timeout issue."),
            ("## Task: add metrics", "Added Prometheus metrics endpoint."),
        ]
    parts = [header]
    parts.append(PINNED_HEADING)
    parts.append(pinned_body)
    parts.append(CONDENSED_HEADING)
    parts.append(condensed_body)
    parts.append(RECENT_HEADING)
    for heading, body in recent_sections:
        parts.append(f"{heading}\n{body}")
    return "\n\n".join(parts) + "\n"


def _make_legacy_flat_file() -> str:
    """Build a legacy flat memory file with no pinned/condensed headings."""
    return (
        "# Agent Memory\n\n"
        "## Task: initial setup\nSet up the development environment.\n\n"
        "## Task: write tests\nWrote unit tests for the core module.\n\n"
        "## Task: deploy\nDeployed to production.\n"
    )


def _make_large_file(section_count: int = 25) -> str:
    """Build an oversized memory file with many sections for condensation tests."""
    recent_sections = [
        (f"## Task: item-{i}", f"Completed work item {i} with detailed notes. " * 10)
        for i in range(section_count)
    ]
    return _make_3region_file(
        pinned_body="- Critical fact A\n- Critical fact B",
        condensed_body="Previous summary of older work.",
        recent_sections=recent_sections,
    )


def _dummy_summarizer(
    condensed_text: str | None,
    evicted: list[Section],
    pinned: str | None,
) -> tuple[str, list[str]]:
    """A test summarizer that produces a short condensed summary."""
    return ("Summarized: all evicted sections condensed.", [])


def _hoisting_summarizer(
    condensed_text: str | None,
    evicted: list[Section],
    pinned: str | None,
) -> tuple[str, list[str]]:
    """A test summarizer that hoists new pinned lines."""
    return ("Summarized: evicted sections condensed.", ["- New critical fact"])


# ── Test: count_sections ─────────────────────────────────────────────────────


class TestCountSections:
    """Tests for the count_sections helper."""

    def test_counts_level_2_headings(self):
        """Counts only ## headings, not # or ### or deeper."""
        text = "# Title\n\n## One\nBody\n\n### Sub\n\n## Two\nBody\n"
        assert count_sections(text) == 2

    def test_empty_text(self):
        """Returns 0 for empty text."""
        assert count_sections("") == 0

    def test_no_headings(self):
        """Returns 0 when there are no ## headings."""
        assert count_sections("Just some plain text\nwith no headings\n") == 0

    def test_many_sections(self):
        """Counts correctly with many sections."""
        text = "\n".join(f"## Section {i}\nBody {i}" for i in range(15))
        assert count_sections(text) == 15

    def test_does_not_count_inline_hash(self):
        """Does not count ## that appears mid-line."""
        text = "Some text ## not a heading\n## Real heading\n"
        assert count_sections(text) == 1


# ── Test: parse_memory ───────────────────────────────────────────────────────


class TestParseMemory:
    """Tests for the parse_memory function."""

    def test_parses_3region_file(self):
        """Correctly splits a valid 3-region memory file."""
        text = _make_3region_file()
        parsed = parse_memory(text)

        assert parsed.header == "# Agent Memory"
        assert parsed.pinned is not None
        assert "Always use UTC timestamps" in parsed.pinned
        assert parsed.condensed is not None
        assert "initial setup" in parsed.condensed
        assert len(parsed.recent) == 3
        assert parsed.recent[0].heading == "## Task: deploy v2"
        assert parsed.recent[2].heading == "## Task: add metrics"

    def test_parses_legacy_flat_file(self):
        """Legacy flat file has pinned=None, condensed=None, all sections in recent."""
        text = _make_legacy_flat_file()
        parsed = parse_memory(text)

        assert parsed.header == "# Agent Memory"
        assert parsed.pinned is None
        assert parsed.condensed is None
        assert len(parsed.recent) == 3
        assert parsed.recent[0].heading == "## Task: initial setup"
        assert parsed.recent[1].heading == "## Task: write tests"
        assert parsed.recent[2].heading == "## Task: deploy"

    def test_header_only_file(self):
        """A file with no ## sections has everything in header."""
        text = "# My Memory\n\nSome preamble text here.\n"
        parsed = parse_memory(text)

        assert "My Memory" in parsed.header
        assert parsed.pinned is None
        assert parsed.condensed is None
        assert parsed.recent == []

    def test_empty_text(self):
        """Empty text parses without error."""
        parsed = parse_memory("")
        assert parsed.header == ""
        assert parsed.pinned is None
        assert parsed.condensed is None
        assert parsed.recent == []

    def test_round_trip_structure(self):
        """Parse then rebuild produces a valid 3-region structure."""
        text = _make_3region_file()
        parsed = parse_memory(text)
        rebuilt = rebuild(
            parsed.header,
            pinned_lines(parsed.pinned),
            parsed.condensed or "",
            parsed.recent,
        )
        reparsed = parse_memory(rebuilt)
        assert reparsed.pinned is not None
        assert reparsed.condensed is not None
        assert len(reparsed.recent) == len(parsed.recent)


# ── Test: pinned_lines ───────────────────────────────────────────────────────


class TestPinnedLines:
    """Tests for the pinned_lines helper."""

    def test_extracts_non_empty_lines(self):
        """Returns only non-empty trimmed lines."""
        pinned = "- Fact one\n\n  - Fact two  \n\n\n- Fact three\n"
        result = pinned_lines(pinned)
        assert result == ["- Fact one", "- Fact two", "- Fact three"]

    def test_none_input(self):
        """Returns empty list for None."""
        assert pinned_lines(None) == []

    def test_empty_string(self):
        """Returns empty list for empty string."""
        assert pinned_lines("") == []

    def test_all_whitespace(self):
        """Returns empty list when all lines are whitespace."""
        assert pinned_lines("   \n  \n\n") == []

    def test_filters_blank_lines(self):
        """Blank lines between content are filtered out."""
        pinned = "first\n\nsecond\n\nthird"
        result = pinned_lines(pinned)
        assert len(result) == 3


# ── Test: merge_pinned ───────────────────────────────────────────────────────


class TestMergePinned:
    """Tests for the merge_pinned helper."""

    def test_appends_new_lines(self):
        """New lines are appended to the existing set."""
        old = ["- Fact A", "- Fact B"]
        hoist = ["- Fact C"]
        result = merge_pinned(old, hoist)
        assert result == ["- Fact A", "- Fact B", "- Fact C"]

    def test_deduplicates(self):
        """Lines already present are not duplicated."""
        old = ["- Fact A", "- Fact B"]
        hoist = ["- Fact A", "- Fact C", "- Fact B"]
        result = merge_pinned(old, hoist)
        assert result == ["- Fact A", "- Fact B", "- Fact C"]

    def test_empty_hoist(self):
        """Empty hoist list returns original unchanged."""
        old = ["- Fact A"]
        result = merge_pinned(old, [])
        assert result == ["- Fact A"]

    def test_empty_old(self):
        """Empty old list with new hoist works correctly."""
        result = merge_pinned([], ["- New fact"])
        assert result == ["- New fact"]

    def test_trims_hoist_lines(self):
        """Hoist lines are trimmed before comparison."""
        old = ["- Fact A"]
        hoist = ["  - Fact A  ", "  - Fact B  "]
        result = merge_pinned(old, hoist)
        assert result == ["- Fact A", "- Fact B"]

    def test_skips_none_and_empty(self):
        """None and empty strings in hoist are skipped."""
        old = ["- Fact A"]
        hoist = ["", "  ", "- Fact B"]
        result = merge_pinned(old, hoist)
        assert result == ["- Fact A", "- Fact B"]


# ── Test: rebuild ────────────────────────────────────────────────────────────


class TestRebuild:
    """Tests for the rebuild function."""

    def test_produces_valid_3region_output(self):
        """Rebuilt file contains all three region headings."""
        result = rebuild(
            "# Agent Memory",
            ["- Fact A", "- Fact B"],
            "Summary of past work.",
            [Section(heading="## Task: latest", body="Did something.")],
        )
        assert PINNED_HEADING in result
        assert CONDENSED_HEADING in result
        assert RECENT_HEADING in result
        assert "- Fact A" in result
        assert "- Fact B" in result
        assert "Summary of past work." in result
        assert "## Task: latest" in result

    def test_empty_pinned_shows_placeholder(self):
        """Empty pinned list shows '_(none yet)_' placeholder."""
        result = rebuild(
            "# Memory",
            [],
            "Some condensed text.",
            [],
        )
        assert "_(none yet)_" in result

    def test_preserves_section_content(self):
        """Recent sections are preserved in output."""
        sections = [
            Section(heading="## Task: one", body="Body one."),
            Section(heading="## Task: two", body="Body two."),
        ]
        result = rebuild("# Memory", ["- Fact"], "Condensed.", sections)
        assert "## Task: one\nBody one." in result
        assert "## Task: two\nBody two." in result

    def test_ends_with_newline(self):
        """Rebuilt file always ends with a newline."""
        result = rebuild("# Memory", [], "Condensed.", [])
        assert result.endswith("\n")

    def test_empty_header(self):
        """Rebuild works with empty header (skips it)."""
        result = rebuild("", ["- Fact"], "Condensed.", [])
        assert result.startswith(PINNED_HEADING)


# ── Test: verify ─────────────────────────────────────────────────────────────


class TestVerify:
    """Tests for the verify-dont-trust gate."""

    def _valid_rebuild(
        self,
        pinned: list[str] | None = None,
        condensed: str | None = None,
        keep: list[Section] | None = None,
    ) -> tuple[str, int, int, list[str], list[str], str, list[Section]]:
        """Build valid arguments for verify that should pass."""
        if pinned is None:
            pinned = ["- Fact A", "- Fact B"]
        if condensed is None:
            # Must be long enough that the rebuilt file exceeds 200 bytes
            condensed = (
                "Summarized history of work including setup, deployment, "
                "and multiple rounds of testing and integration."
            )
        if keep is None:
            keep = [
                Section(
                    heading="## Task: recent work",
                    body="Completed the recent task with detailed notes and results.",
                )
            ]
        rebuilt = rebuild("# Agent Memory", pinned, condensed, keep)
        new_bytes = len(rebuilt.encode("utf-8"))
        # Old bytes must be much larger for the 0.95 check to pass
        old_bytes = new_bytes * 3
        return (rebuilt, new_bytes, old_bytes, pinned, pinned, condensed, keep)

    def test_accepts_valid_rewrite(self):
        """Verify passes for a correctly built rewrite."""
        args = self._valid_rebuild()
        result = verify(*args)
        assert result.ok is True
        assert result.reason == ""

    def test_rejects_structure_missing_region(self):
        """Rejects when rebuilt file is missing pinned or condensed region."""
        # Build a file without the pinned heading
        text = "# Memory\n\n## Some section\nBody\n"
        keep: list[Section] = []
        result = verify(
            rebuilt=text,
            new_bytes=len(text.encode("utf-8")),
            old_bytes=10000,
            old_pinned_lines=[],
            merged_pinned=[],
            condensed="Something.",
            keep=keep,
        )
        assert result.ok is False
        assert result.reason == "structure-missing-region"

    def test_rejects_too_small(self):
        """Rejects when new_bytes is 200 or less."""
        args = self._valid_rebuild()
        rebuilt, _, old_bytes, old_pinned, merged, condensed, keep = args
        result = verify(
            rebuilt=rebuilt,
            new_bytes=100,
            old_bytes=old_bytes,
            old_pinned_lines=old_pinned,
            merged_pinned=merged,
            condensed=condensed,
            keep=keep,
        )
        assert result.ok is False
        assert result.reason == "too-small"

    def test_rejects_empty_condensed(self):
        """Rejects when condensed text is empty or whitespace."""
        pinned = ["- Fact A", "- Fact B", "- Fact C is a longer line for size"]
        keep = [
            Section(
                heading="## Task: recent work",
                body="Completed the recent task with detailed notes and results "
                "spanning multiple lines of content for size.",
            )
        ]
        # Build with non-empty condensed in the file but pass empty to verify
        file_condensed = "placeholder text that is reasonably long for the file"
        rebuilt = rebuild("# Agent Memory", pinned, file_condensed, keep)
        new_bytes = len(rebuilt.encode("utf-8"))
        old_bytes = new_bytes * 3
        result = verify(
            rebuilt=rebuilt,
            new_bytes=new_bytes,
            old_bytes=old_bytes,
            old_pinned_lines=pinned,
            merged_pinned=pinned,
            condensed="   ",  # empty/whitespace condensed
            keep=keep,
        )
        assert result.ok is False
        assert result.reason == "empty-condensed"

    def test_rejects_not_smaller(self):
        """Rejects when new file is not at least 5% smaller."""
        args = self._valid_rebuild()
        rebuilt, new_bytes, _, old_pinned, merged, condensed, keep = args
        # Set old_bytes to be same as new_bytes (not smaller)
        result = verify(
            rebuilt=rebuilt,
            new_bytes=new_bytes,
            old_bytes=new_bytes,  # same size means not smaller
            old_pinned_lines=old_pinned,
            merged_pinned=merged,
            condensed=condensed,
            keep=keep,
        )
        assert result.ok is False
        assert result.reason == "not-smaller"

    def test_rejects_pinned_line_dropped(self):
        """Rejects when an old pinned line is not in the rebuilt file."""
        keep = [
            Section(
                heading="## Task: recent work item",
                body="Completed the recent task with lots of detailed notes "
                "and comprehensive results spanning content.",
            )
        ]
        # Build with only Fact A in the file but old_pinned has A and B
        condensed = (
            "Long condensed summary of all past work including setup, "
            "deployment, and multiple integration steps."
        )
        rebuilt = rebuild("# Agent Memory", ["- Fact A"], condensed, keep)
        new_bytes = len(rebuilt.encode("utf-8"))
        old_bytes = new_bytes * 3
        result = verify(
            rebuilt=rebuilt,
            new_bytes=new_bytes,
            old_bytes=old_bytes,
            old_pinned_lines=["- Fact A", "- Fact B"],  # B is missing
            merged_pinned=["- Fact A", "- Fact B"],
            condensed=condensed,
            keep=keep,
        )
        assert result.ok is False
        assert result.reason == "pinned-line-dropped"

    def test_rejects_recent_section_altered(self):
        """Rejects when a kept recent section does not match byte-for-byte."""
        pinned = ["- Fact A", "- Fact B"]
        condensed = (
            "Long condensed summary of all past work including setup, "
            "deployment, and multiple integration steps."
        )
        keep_original = [
            Section(
                heading="## Task: recent work item",
                body="Original body with detailed content for the task.",
            )
        ]
        keep_altered = [
            Section(
                heading="## Task: recent work item",
                body="Altered body with different content for the task!",
            )
        ]
        rebuilt = rebuild("# Agent Memory", pinned, condensed, keep_altered)
        new_bytes = len(rebuilt.encode("utf-8"))
        old_bytes = new_bytes * 3
        result = verify(
            rebuilt=rebuilt,
            new_bytes=new_bytes,
            old_bytes=old_bytes,
            old_pinned_lines=pinned,
            merged_pinned=pinned,
            condensed=condensed,
            keep=keep_original,  # expect original, but rebuilt has altered
        )
        assert result.ok is False
        assert result.reason == "recent-section-altered"


# ── Test: should_condense ────────────────────────────────────────────────────


class TestShouldCondense:
    """Tests for the MemoryReflector.should_condense threshold logic."""

    def test_below_min_bytes_never_condenses(self):
        """Files smaller than min_bytes never trigger condensation."""
        reflector = MemoryReflector(ReflectSettings(min_bytes=4096))
        assert reflector.should_condense(file_bytes=2000, section_count=100) is False

    def test_above_byte_trigger_condenses(self):
        """Files exceeding byte_trigger_pct of BUDGET_BYTES trigger condensation."""
        reflector = MemoryReflector(ReflectSettings(byte_trigger_pct=80))
        threshold = (BUDGET_BYTES * 80) // 100
        assert reflector.should_condense(file_bytes=threshold + 1, section_count=1) is True

    def test_at_byte_trigger_does_not_condense(self):
        """Files exactly at the byte trigger do not condense (must exceed)."""
        reflector = MemoryReflector(ReflectSettings(byte_trigger_pct=80))
        threshold = (BUDGET_BYTES * 80) // 100
        assert reflector.should_condense(file_bytes=threshold, section_count=1) is False

    def test_above_section_trigger_condenses(self):
        """Files exceeding section_trigger (above min_bytes) trigger condensation."""
        reflector = MemoryReflector(
            ReflectSettings(min_bytes=4096, section_trigger=20)
        )
        assert reflector.should_condense(file_bytes=5000, section_count=21) is True

    def test_at_section_trigger_does_not_condense(self):
        """Files at exactly section_trigger do not trigger (must exceed)."""
        reflector = MemoryReflector(
            ReflectSettings(min_bytes=4096, section_trigger=20)
        )
        assert reflector.should_condense(file_bytes=5000, section_count=20) is False

    def test_below_both_triggers_does_not_condense(self):
        """Files below both triggers do not condense."""
        reflector = MemoryReflector(
            ReflectSettings(min_bytes=4096, byte_trigger_pct=80, section_trigger=20)
        )
        assert reflector.should_condense(file_bytes=5000, section_count=5) is False


# ── Test: condense pipeline ──────────────────────────────────────────────────


class TestCondensePipeline:
    """Tests for the full MemoryReflector.condense pipeline."""

    def test_nothing_to_evict(self):
        """Returns nothing-to-evict when fewer sections than recent_keep."""
        reflector = MemoryReflector(ReflectSettings(recent_keep=5))
        text = _make_3region_file(
            recent_sections=[
                ("## Task: one", "Body one."),
                ("## Task: two", "Body two."),
            ]
        )
        result = reflector.condense("agent-1", text, _dummy_summarizer)
        assert result.condensed is False
        assert result.reason == "nothing-to-evict"

    def test_successful_condense(self):
        """Full pipeline succeeds with enough sections to evict."""
        reflector = MemoryReflector(ReflectSettings(recent_keep=2))
        text = _make_large_file(section_count=10)
        result = reflector.condense("agent-1", text, _dummy_summarizer)
        assert result.condensed is True
        assert result.reason == "condensed"
        assert result.old_bytes is not None
        assert result.new_bytes is not None
        assert result.new_bytes < result.old_bytes

    def test_successful_condense_returns_rebuilt_text(self):
        """Full pipeline returns rebuilt_text on success."""
        reflector = MemoryReflector(ReflectSettings(recent_keep=2))
        text = _make_large_file(section_count=10)
        result = reflector.condense("agent-1", text, _dummy_summarizer)
        assert result.condensed is True
        assert result.rebuilt_text is not None
        assert len(result.rebuilt_text) > 0
        # Rebuilt text should be a valid 3-region file
        assert PINNED_HEADING in result.rebuilt_text
        assert CONDENSED_HEADING in result.rebuilt_text
        assert RECENT_HEADING in result.rebuilt_text
        # Byte length should match new_bytes
        assert len(result.rebuilt_text.encode("utf-8")) == result.new_bytes

    def test_nothing_to_evict_has_no_rebuilt_text(self):
        """Returns rebuilt_text=None when nothing to evict."""
        reflector = MemoryReflector(ReflectSettings(recent_keep=5))
        text = _make_3region_file(
            recent_sections=[
                ("## Task: one", "Body one."),
                ("## Task: two", "Body two."),
            ]
        )
        result = reflector.condense("agent-1", text, _dummy_summarizer)
        assert result.condensed is False
        assert result.rebuilt_text is None

    def test_condense_with_hoist(self):
        """Pipeline correctly hoists new pinned lines from summarizer."""
        reflector = MemoryReflector(ReflectSettings(recent_keep=2))
        text = _make_large_file(section_count=10)
        result = reflector.condense("agent-1", text, _hoisting_summarizer)
        assert result.condensed is True

    def test_condense_preserves_agent_id(self):
        """Result carries the correct agent_id."""
        reflector = MemoryReflector(ReflectSettings(recent_keep=2))
        text = _make_large_file(section_count=10)
        result = reflector.condense("my-agent-42", text, _dummy_summarizer)
        assert result.id == "my-agent-42"


# ── Test: types importability ────────────────────────────────────────────────


class TestTypesImportable:
    """Verify all types are importable from nexus.memory.reflector_types."""

    def test_all_types_importable(self):
        """All expected types can be imported."""
        import nexus.memory.reflector_types as rt

        # Verify all expected types exist and are usable
        settings = rt.ReflectSettings()
        assert settings.enabled is True
        result = rt.ReflectResult(id="test", condensed=False, reason="test")
        assert result.id == "test"
        section = rt.Section(heading="## Test", body="body")
        assert section.heading == "## Test"
        memory = rt.ParsedMemory(header="# H")
        assert memory.header == "# H"
