"""Each package must import first in a fresh interpreter, whatever the suite imported before it."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize(
    "module",
    ["nexus.obsidian", "nexus.tools", "nexus.tools.obsidian", "nexus.runtime", "nexus.models"],
)
def test_module_imports_first_in_a_fresh_interpreter(module):
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr[-600:]
