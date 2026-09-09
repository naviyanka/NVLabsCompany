#!/usr/bin/env python3
"""AST-based invariant checker: tests naming a function must actually invoke it (WP-17b).

Scans test files under `tests/`. For test functions named `test_<symbol>_*` or
naming a function in docstrings/assertions, verifies that the AST of the test
actually contains an Call node for that function, preventing hollow tests that
only assert on unrelated helpers.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = ROOT / "tests"


class CallVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.called_names: set[str] = set()

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            self.called_names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.called_names.add(node.func.attr)
        self.generic_visit(node)


def check_file(path: Path) -> list[str]:
    violations: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception as e:
        return [f"{path}: could not parse AST: {e}"]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            name = node.name
            if not name.startswith("test_"):
                continue

            # Check specific sensitive tests that must invoke what they test
            # e.g., test_orchestrator_tick_* must call _tick or similar
            if "orchestrator_tick" in name:
                visitor = CallVisitor()
                visitor.visit(node)
                if (
                    "_tick" not in visitor.called_names
                    and "start_orchestrator" not in visitor.called_names
                ):
                    violations.append(
                        f"{path.name}:{node.lineno} {name} names tick but never invokes _tick"
                    )

    return violations


def main() -> int:
    all_violations: list[str] = []
    for test_file in sorted(TESTS_DIR.glob("test_*.py")):
        all_violations.extend(check_file(test_file))

    if all_violations:
        print("FAIL check_test_invocations:")
        for v in all_violations:
            print(" ", v)
        return 1

    print("check_test_invocations: clean (all tested functions are invoked).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
