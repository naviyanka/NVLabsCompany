"""Split assistant text into ordered language runs for TTS routing.

Devanagari runs go to the Hindi voice, everything else (Latin words, identifiers,
filenames, code) to the English voice. Digits, punctuation and spaces stay with the
run they sit in, so IDs and filenames are never cut. Text is otherwise unchanged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE = re.compile(r"^\s*```\w*\s*$", re.MULTILINE)
_MARKUP = re.compile(r"[*#>`]+")


@dataclass(frozen=True)
class Segment:
    language: str  # "hi" | "en"
    text: str


def clean(text: str) -> str:
    """Drop markdown syntax characters; keep every word, ID, path and code token."""
    return _MARKUP.sub("", _FENCE.sub("", text)).strip()


def _lang(ch: str) -> str | None:
    if "\u0900" <= ch <= "\u097f":
        return "hi"
    if ch.isalpha():
        return "en"
    return None  # neutral: digits, punctuation, whitespace


def split(text: str) -> list[Segment]:
    text = clean(text)
    out: list[Segment] = []
    current, buf = None, ""
    for ch in text:
        lang = _lang(ch)
        if lang is not None and current is not None and lang != current:
            out.append(Segment(current, buf))
            buf = ""
        if lang is not None:
            current = lang
        buf += ch
    if buf.strip():
        out.append(Segment(current or "en", buf))
    # A run that is only punctuation or digits carries nothing to say alone.
    merged: list[Segment] = []
    for seg in out:
        if merged and not any(c.isalpha() for c in seg.text):
            merged[-1] = Segment(merged[-1].language, merged[-1].text + seg.text)
        else:
            merged.append(seg)
    return [s for s in merged if any(c.isalnum() for c in s.text)]
