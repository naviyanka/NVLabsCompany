"""YAML frontmatter extraction for vault notes (ADR 0002 §13).

``MarkdownParser`` in ``nexus.knowledge.parsers`` splits on markdown structure
and has no frontmatter awareness, so it would chunk a ``---`` block as content.
This module strips the block first and hands back the body.

Same shape as ``nexus.templates.registry._parse_template``, with one deliberate
difference: a note without frontmatter is valid here and yields empty metadata.
Humans author these files by hand, and refusing to read a note because it lacks
a metadata block would make the vault unusable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

_DELIMITER = "---"


class _NoAliasLoader(yaml.SafeLoader):
    """SafeLoader that refuses YAML aliases.

    ``safe_load`` blocks arbitrary object construction but still expands
    aliases, and alias expansion is multiplicative: a 190-byte frontmatter block
    of five nested 10-element alias lists expands to ~580 KB of objects, and each
    further level multiplies by ten. The note size cap cannot bound that, so
    aliases are refused outright — a metadata block has no legitimate use for
    them.
    """

    def compose_node(self, parent: object, index: object) -> object:
        if self.check_event(yaml.events.AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "YAML aliases are not allowed in note frontmatter",
                event.start_mark,
            )
        return super().compose_node(parent, index)  # type: ignore[arg-type]


@dataclass
class ParsedNote:
    """A vault note split into frontmatter and body.

    Attributes:
        metadata: Parsed frontmatter mapping; empty when the note has none.
        body: Markdown body with the frontmatter block removed.
    """

    metadata: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @property
    def nexus_id(self) -> str | None:
        """The ``nexus_id`` frontmatter value, if the note carries one."""
        value = self.metadata.get("nexus_id")
        return str(value) if value is not None else None

    @property
    def doc_type(self) -> str | None:
        """The ``type`` frontmatter value (ADR 0002 §7), if present."""
        value = self.metadata.get("type")
        return str(value) if value is not None else None

    @property
    def title(self) -> str | None:
        """The ``title`` frontmatter value, if present."""
        value = self.metadata.get("title")
        return str(value) if value is not None else None


def parse_note(content: str) -> ParsedNote:
    """Split note text into frontmatter metadata and markdown body.

    A note is treated as having frontmatter only when it opens with ``---`` on
    its own line and a closing ``---`` line follows. Anything else is all body,
    which keeps a note that merely uses a horizontal rule from being misread.

    Malformed YAML inside an otherwise well-formed block yields empty metadata
    rather than raising: one bad note must not fail a whole vault scan. The
    caller sees empty metadata, so the note indexes with no ``nexus_id`` and is
    reported as needing attention. This covers deep nesting (``RecursionError``)
    and aliases (refused by :class:`_NoAliasLoader`) as well as syntax errors.

    Args:
        content: Raw note text.

    Returns:
        A :class:`ParsedNote`. For a note without frontmatter, ``metadata`` is
        empty and ``body`` is the input unchanged.
    """
    if not content:
        return ParsedNote()

    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != _DELIMITER:
        return ParsedNote(body=content)

    closing_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == _DELIMITER:
            closing_index = index
            break

    if closing_index is None:
        # Opening delimiter with no close: not frontmatter, just content.
        return ParsedNote(body=content)

    block = "".join(lines[1:closing_index])
    body = "".join(lines[closing_index + 1 :])

    try:
        loaded = yaml.load(block, Loader=_NoAliasLoader)  # noqa: S506 - alias-refusing SafeLoader subclass
    except (yaml.YAMLError, RecursionError, ValueError, TypeError):
        # RecursionError is the one that matters: PyYAML recurses per nesting
        # level, so a 1 KB note of 500 nested brackets — far under the size cap —
        # raises it. Catching only YAMLError would let one malformed note abort
        # a whole vault scan, which this function's contract forbids.
        return ParsedNote(body=body)

    metadata = loaded if isinstance(loaded, dict) else {}
    return ParsedNote(metadata=metadata, body=body)
