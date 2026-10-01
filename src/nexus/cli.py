"""``nexus`` command line. Only ``doctor`` so far."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["doctor"]:
        from nexus.voice.doctor import main as doctor

        return doctor(argv[1:])
    sys.stderr.write("usage: nexus doctor --voice [--json] [--company <id>]\n")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
