"""Buffers streamed assistant text into speakable sentence or clause chunks.

Only text handed to :meth:`feed` is ever spoken, so callers pass user-visible reply
text and nothing else. Boundaries are sentence ends (``. ! ? \u0964``) and newlines; a
long run without one is cut at a clause mark or space so speech starts promptly.
Dots inside identifiers, filenames and numbers (``report_v2.pdf``, ``3.5``) do not
end a sentence.
"""

from __future__ import annotations

import re

_END = re.compile(r"[.!?\u0964](?=\s)|\n")
MIN_CHARS = 24  # avoid speaking fragments like "Yes."
SOFT_MAX = 200


class SentenceChunker:
    def __init__(self) -> None:
        self.buf = ""

    def feed(self, text: str) -> list[str]:
        self.buf += text
        out: list[str] = []
        while True:
            cut = self._cut()
            if cut is None:
                return out
            piece, self.buf = self.buf[:cut], self.buf[cut:]
            if piece.strip():
                out.append(piece.strip())

    def _cut(self) -> int | None:
        for m in _END.finditer(self.buf):
            if m.end() >= MIN_CHARS or m.group() == "\n":
                return m.end()
        if len(self.buf) > SOFT_MAX:
            head = self.buf[:SOFT_MAX]
            for sep in (", ", "; ", "\u2014 ", " "):
                i = head.rfind(sep)
                if i > MIN_CHARS:
                    return i + len(sep)
            return SOFT_MAX
        return None

    def flush(self) -> list[str]:
        rest, self.buf = self.buf.strip(), ""
        return [rest] if rest else []
