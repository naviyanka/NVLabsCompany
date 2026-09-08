"""Wikilink extraction for vault notes (ADR 0002 §14, proposal §7).

Obsidian's ``[[Target]]`` syntax is how a human states that two notes are
related, so it is the vault's own relationship mechanism and NEXUS reads it
rather than asking for the same information twice.

What comes out is a list of link *targets* — the text a human typed — not
resolved document ids. Resolution happens where the graph is derived
(``api/routes/memory_graph.py``), because a link may point at a note that does
not exist yet and that dangling state is information, not an error.

Nothing here writes to the vault or to the database.
"""

from __future__ import annotations

import re
from typing import Any

# Targets per note. A note listing thousands of links is a generated index, and
# fanning all of them into the derived graph would swamp it; the cap bounds the
# derived edge count without needing a second guard downstream.
MAX_LINKS_PER_NOTE = 200

# Longest target text kept. Obsidian itself is bounded by the filesystem's path
# limit, so anything longer cannot name a real note.
MAX_TARGET_LENGTH = 512

# ``[[Target]]``, ``[[Target|Alias]]``, ``[[Target#Heading]]``, and the embed
# form ``![[Target]]``. The alias and heading are display concerns: two notes
# are related whether or not the link renders under a different label.
_WIKILINK = re.compile(r"!?\[\[([^\[\]]+?)\]\]")

# Fenced blocks (``` or ~~~) and inline code spans. A link inside code is being
# shown, not made — a note documenting the wikilink syntax is not related to a
# note called "Target".
_FENCED = re.compile(r"^([ \t]*)(`{3,}|~{3,})[^\n]*\n.*?(?:^[ \t]*\2[^\n]*$|\Z)", re.S | re.M)
_INLINE_CODE = re.compile(r"(`+)(?:.|\n)*?\1")


def normalize_target(raw: str) -> str:
    """Reduce a raw link target to the note it names.

    Strips the alias (``|``) and heading/block (``#``, ``^``) parts, the ``.md``
    extension Obsidian allows but does not require, and surrounding whitespace.

    Args:
        raw: Link text as written between the brackets.

    Returns:
        The bare target, or an empty string when nothing usable remains.
    """
    target = raw.split("|", 1)[0]
    target = re.split(r"[#^]", target, maxsplit=1)[0]
    target = target.strip().strip("/")
    if target.lower().endswith(".md"):
        target = target[:-3]
    return target[:MAX_TARGET_LENGTH].strip()


def _strip_code(body: str) -> str:
    """Blank out code so links shown as examples are not read as relationships.

    Replaces each span with newlines rather than deleting it, keeping the rest of
    the body's line structure intact for anything that looks at positions later.
    """

    def blank(match: re.Match[str]) -> str:
        return "\n" * match.group(0).count("\n")

    return _INLINE_CODE.sub(blank, _FENCED.sub(blank, body))


def extract_wikilinks(body: str) -> list[str]:
    """Return the note targets a body links to, in order, without duplicates.

    Args:
        body: Markdown body with frontmatter already removed.

    Returns:
        Normalized link targets, first occurrence order preserved, capped at
        :data:`MAX_LINKS_PER_NOTE`.
    """
    if not body or "[[" not in body:
        return []

    seen: set[str] = set()
    targets: list[str] = []
    for match in _WIKILINK.finditer(_strip_code(body)):
        target = normalize_target(match.group(1))
        if not target:
            continue
        key = target.casefold()
        if key in seen:
            continue
        seen.add(key)
        targets.append(target)
        if len(targets) >= MAX_LINKS_PER_NOTE:
            break
    return targets


def frontmatter_links(metadata: dict[str, Any]) -> list[str]:
    """Return targets declared in frontmatter ``related``.

    ADR 0002 §14 counts explicit frontmatter relationships alongside inline
    wikilinks. A human may write them either as bare titles or as wikilinks, so
    both forms are accepted.

    Args:
        metadata: Parsed frontmatter mapping.

    Returns:
        Normalized targets, first occurrence order preserved.
    """
    raw = metadata.get("related")
    if raw is None:
        return []
    values = raw if isinstance(raw, list) else [raw]

    seen: set[str] = set()
    targets: list[str] = []
    for value in values:
        if not isinstance(value, (str, int, float)):
            # A mapping or nested list under `related` is a malformed note, and
            # one bad note must not fail the scan (see frontmatter.parse_note).
            continue
        text = str(value).strip()
        inline = extract_wikilinks(text)
        for target in inline or [normalize_target(text)]:
            if not target:
                continue
            key = target.casefold()
            if key in seen:
                continue
            seen.add(key)
            targets.append(target)
            if len(targets) >= MAX_LINKS_PER_NOTE:
                return targets
    return targets


def note_links(metadata: dict[str, Any], body: str) -> list[str]:
    """Every target a note relates to, from its body and its frontmatter.

    Args:
        metadata: Parsed frontmatter mapping.
        body: Markdown body with frontmatter removed.

    Returns:
        Normalized targets, body links first, capped at
        :data:`MAX_LINKS_PER_NOTE`.
    """
    targets = extract_wikilinks(body)
    seen = {target.casefold() for target in targets}
    for target in frontmatter_links(metadata):
        if target.casefold() in seen:
            continue
        seen.add(target.casefold())
        targets.append(target)
        if len(targets) >= MAX_LINKS_PER_NOTE:
            break
    return targets
