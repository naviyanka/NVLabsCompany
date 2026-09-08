"""Small atomic JSON persistence helpers for process registries."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def dump_json(path: Path, value: Any) -> None:
    """Write JSON atomically so a crash cannot leave a partial registry."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.unlink(temporary)
        raise


def load_json(path: Path) -> Any:
    """Load JSON from path."""
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)
