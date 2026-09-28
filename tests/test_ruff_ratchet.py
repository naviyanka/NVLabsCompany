"""The ruff ratchet fails only when a file gains violations of a rule."""

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ruff_ratchet.py"
spec = importlib.util.spec_from_file_location("ruff_ratchet", SCRIPT)
ratchet = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ratchet)


def test_regressions_flags_only_increases_and_new_files() -> None:
    baseline = {"a.py": {"E501": 2, "F401": 1}}
    current = {
        "a.py": {"E501": 2, "F401": 2, "I001": 1},  # F401 grew, I001 is new
        "b.py": {"E501": 1},  # a file absent from the baseline must be clean
    }
    assert ratchet.regressions(current, baseline) == [
        ("a.py", "F401", 2, 1),
        ("a.py", "I001", 1, 0),
        ("b.py", "E501", 1, 0),
    ]


def test_fewer_violations_pass() -> None:
    assert ratchet.regressions({"a.py": {"E501": 1}}, {"a.py": {"E501": 2}}) == []
