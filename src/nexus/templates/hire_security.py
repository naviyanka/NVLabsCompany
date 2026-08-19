"""Security validation functions for hire manifests.

Provides standalone validation utilities for individual manifest fields,
useful for pre-validation and security boundary checking outside of the
full Pydantic model validation.
"""

from __future__ import annotations

from nexus.templates.hire_manifest import FLAG_RE, MODEL_RE, SAFE_FLAG_NAMES


def is_safe_flag(token: str) -> bool:
    """Check if a flag token is in the safe allowlist (case-insensitive name match).

    Only tokens that start with '-' and whose name (before any '=') is in
    SAFE_FLAG_NAMES are considered safe.
    """
    if not token.startswith("-"):
        return False
    name = token.split("=", 1)[0].lower()
    return name in SAFE_FLAG_NAMES


def validate_command_flags(flags: list[str]) -> tuple[bool, list[str]]:
    """Validate a list of command flags against the security rules.

    Applies the full default-deny allowlist logic:
    - Every token must match FLAG_RE
    - First entry must start with '-'
    - Flag-shaped tokens must be in SAFE_FLAG_NAMES
    - Bare values allowed only immediately after an allowed flag without '='

    Returns:
        A tuple of (ok, errors) where ok is True if all flags pass validation.
    """
    errors: list[str] = []

    if len(flags) > 16:
        errors.append("commandFlags must have at most 16 items")
        return (False, errors)

    value_allowed = False
    for i, f in enumerate(flags):
        if not FLAG_RE.match(f):
            errors.append(f"flag {f!r} contains disallowed characters")
            value_allowed = False
            continue
        if i == 0 and not f.startswith("-"):
            errors.append("commandFlags must start with a flag (e.g. '--model')")
            value_allowed = False
            continue
        if f.startswith("-"):
            name = f.split("=", 1)[0].lower()
            if name not in SAFE_FLAG_NAMES:
                errors.append(
                    f"flag {f!r} not in safe-flag allowlist "
                    f"({', '.join(sorted(SAFE_FLAG_NAMES))})"
                )
                value_allowed = False
            else:
                value_allowed = "=" not in f
        else:
            if not value_allowed:
                errors.append(
                    f"value {f!r} not allowed here (must follow an allowed flag)"
                )
            value_allowed = False

    return (len(errors) == 0, errors)


def validate_model_id(model: str) -> tuple[bool, str]:
    """Validate a model ID against the safe character set.

    Returns:
        A tuple of (ok, reason) where ok is True if the model ID is valid,
        and reason is an empty string on success or a description of the issue.
    """
    if MODEL_RE.match(model):
        return (True, "")
    return (False, "model contains disallowed characters")
