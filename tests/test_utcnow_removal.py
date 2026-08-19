"""Test that datetime.utcnow() has been fully removed from the codebase.

Scans all Python source files under src/nexus/ to ensure no occurrences
of the deprecated datetime.utcnow() pattern remain. The correct replacement
is datetime.now(timezone.utc).
"""

import os
from pathlib import Path


def test_no_datetime_utcnow_in_source() -> None:
    """Verify zero occurrences of datetime.utcnow() in src/nexus/."""
    src_dir = Path(__file__).parent.parent / "src" / "nexus"
    violations: list[str] = []

    for root, _dirs, files in os.walk(src_dir):
        for filename in files:
            if not filename.endswith(".py"):
                continue
            filepath = Path(root) / filename
            content = filepath.read_text(encoding="utf-8")
            for lineno, line in enumerate(content.splitlines(), start=1):
                if "datetime.utcnow()" in line:
                    rel_path = filepath.relative_to(src_dir.parent.parent)
                    violations.append(f"{rel_path}:{lineno}: {line.strip()}")

    assert violations == [], (
        f"Found {len(violations)} occurrence(s) of datetime.utcnow():\n"
        + "\n".join(violations)
    )


def test_timezone_utc_pattern_used_in_models() -> None:
    """Verify model files use datetime.now(timezone.utc) in Field defaults."""
    models_dir = Path(__file__).parent.parent / "src" / "nexus" / "models"
    checked_files = 0

    for filepath in models_dir.glob("*.py"):
        if filepath.name == "__init__.py":
            continue
        content = filepath.read_text(encoding="utf-8")
        if "default_factory" not in content:
            continue
        checked_files += 1
        # If the file has datetime fields, it should import timezone
        if "datetime" in content and "Field(" in content:
            assert "timezone" in content, (
                f"{filepath.name} uses datetime fields but does not "
                "import timezone"
            )

    # Ensure we actually checked some files
    assert checked_files > 0, "No model files with default_factory found"


def test_no_utcnow_in_governance() -> None:
    """Verify governance modules use timezone-aware datetimes."""
    gov_dir = Path(__file__).parent.parent / "src" / "nexus" / "governance"
    violations: list[str] = []

    for filepath in gov_dir.glob("*.py"):
        content = filepath.read_text(encoding="utf-8")
        for lineno, line in enumerate(content.splitlines(), start=1):
            if "utcnow()" in line and not line.strip().startswith("#"):
                rel_path = filepath.relative_to(gov_dir.parent.parent.parent)
                violations.append(f"{rel_path}:{lineno}: {line.strip()}")

    assert violations == [], (
        f"Found {len(violations)} utcnow() in governance:\n"
        + "\n".join(violations)
    )
