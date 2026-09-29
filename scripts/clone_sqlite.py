"""Make a private, transactionally consistent copy of the SQLite database in DATABASE_URL.

    DATABASE_URL=... python scripts/clone_sqlite.py <destination-file>

Uses SQLite's online backup API on a read-only source connection, so an active database is
copied consistently and the source is never written. Rows are copied verbatim: encrypted
values stay encrypted and are never decrypted, hashed or read here. Nothing about the
source (URL, path, contents) is printed; failures use fixed messages.
"""

import os
import re
import sqlite3
import sys
from pathlib import Path


def source_path(url: str) -> Path | None:
    m = re.match(r"^sqlite[^:]*:///(.+?)(?:\?.*)?$", url)
    if not m or m.group(1) == ":memory:":
        return None
    return Path(m.group(1))


def clone(src: Path, dst: Path) -> None:
    if dst.exists():
        raise FileExistsError
    source = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(dst)
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()


def main() -> int:
    src = source_path(os.environ.get("DATABASE_URL", ""))
    if len(sys.argv) != 2 or src is None:
        print("FAIL  isolated mode needs a file-based SQLite DATABASE_URL and one destination path")
        return 2
    if not src.is_file():
        print("FAIL  the SQLite database file does not exist")
        return 2
    try:
        clone(src, Path(sys.argv[1]))
    except (sqlite3.Error, OSError):
        print("FAIL  could not back up the database")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
