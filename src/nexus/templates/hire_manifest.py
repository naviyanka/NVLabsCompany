"""Hire Manifests - portable agent role templates (manifest spec v1).

A hire manifest is a small JSON document that describes a role-configured agent
(name, provider, model, flags, goal, budget) so it can be shared as a file or
imported into the NEXUS system.

Security model: a manifest is untrusted input. All fields are length/shape-capped,
command flags use a default-deny allowlist, and model IDs reject shell metacharacters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field, ValidationError, field_validator

HIRE_SPEC_V1 = "nexus/hire@1"

# Model ID allowed characters - must reject shell metacharacters.
# Real model ids: claude-sonnet-4-6[1m], Gemini 3.1 Pro (High), openai/gpt-4o
MODEL_RE = re.compile(r"^[A-Za-z0-9 ._()[\]/:@+-]{1,80}$")

# Flag token characters (no quotes, backticks, semicolons, pipes, etc.)
FLAG_RE = re.compile(r"^[A-Za-z0-9._/=:,@+-]{1,100}$")

# Default-deny flag allowlist - ONLY these flag names can appear in manifests
SAFE_FLAG_NAMES: frozenset[str] = frozenset([
    "--model",
    "--max-turns",
    "--output-format",
    "--verbose",
])

# Known valid providers (from AgentProviderID, excluding 'custom' for security)
KNOWN_PROVIDERS: frozenset[str] = frozenset([
    "claude",
    "codex",
    "grok",
    "kimi",
    "antigravity",
    "qwen",
    "opencode",
    "crush",
    "pi",
    "copilot",
])


class HireManifest(BaseModel):
    """Portable agent role template - a JSON spec describing a configured agent role."""

    spec: str = HIRE_SPEC_V1
    name: str = Field(..., min_length=1, max_length=40)
    description: Optional[str] = Field(None, max_length=200)
    goal: Optional[str] = Field(None, max_length=4000)
    provider: Optional[str] = None
    model: Optional[str] = Field(None, max_length=80)
    command_flags: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    isolate: bool = False
    token_cap: Optional[int] = Field(None, gt=0, le=10_000_000_000)
    author: Optional[str] = Field(None, max_length=80)
    homepage: Optional[str] = Field(None, max_length=300)

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        """Validate model ID against safe character set."""
        if v is not None and not MODEL_RE.match(v):
            raise ValueError("model contains disallowed characters")
        return v

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, v: Optional[str]) -> Optional[str]:
        """Validate provider against known provider list."""
        if v is not None and v not in KNOWN_PROVIDERS:
            raise ValueError(
                f"provider must be one of: {', '.join(sorted(KNOWN_PROVIDERS))}"
            )
        return v

    @field_validator("command_flags")
    @classmethod
    def validate_flags(cls, flags: list[str]) -> list[str]:
        """Validate command flags against the default-deny safe-flag allowlist.

        Rules:
        - Max 16 items
        - Every token must match FLAG_RE (no shell metacharacters)
        - First entry must start with '-'
        - Flag-shaped tokens must be in SAFE_FLAG_NAMES (case-insensitive name match)
        - Bare values allowed only immediately after an allowed --flag without '='
        """
        if len(flags) > 16:
            raise ValueError("commandFlags must have at most 16 items")
        value_allowed = False
        for i, f in enumerate(flags):
            if not FLAG_RE.match(f):
                raise ValueError(f"flag {f!r} contains disallowed characters")
            if i == 0 and not f.startswith("-"):
                raise ValueError("commandFlags must start with a flag (e.g. '--model')")
            if f.startswith("-"):
                name = f.split("=", 1)[0].lower()
                if name not in SAFE_FLAG_NAMES:
                    raise ValueError(
                        f"flag {f!r} not in safe-flag allowlist "
                        f"({', '.join(sorted(SAFE_FLAG_NAMES))})"
                    )
                value_allowed = "=" not in f  # --flag value form takes next token
            else:
                if not value_allowed:
                    raise ValueError(
                        f"value {f!r} not allowed here (must follow an allowed flag)"
                    )
                value_allowed = False  # consume the value slot
        return flags

    @field_validator("capabilities")
    @classmethod
    def validate_capabilities(cls, v: list[str]) -> list[str]:
        """Validate capabilities list (max 12 items, each truncated to 40 chars)."""
        if len(v) > 12:
            raise ValueError("capabilities must have at most 12 items")
        return [c[:40] for c in v]

    @field_validator("homepage")
    @classmethod
    def validate_homepage(cls, v: Optional[str]) -> Optional[str]:
        """Validate homepage URL is https."""
        if v is not None and not v.startswith("https://"):
            raise ValueError("homepage must be https")
        return v


@dataclass
class HireValidation:
    """Result of validating a hire manifest from raw input."""

    ok: bool
    manifest: HireManifest | None = None
    errors: list[str] = field(default_factory=list)


def validate_hire_manifest(raw: dict) -> HireValidation:
    """Validate a raw dictionary into a HireManifest.

    Wraps Pydantic validation errors into a HireValidation result object.
    Returns HireValidation with ok=True and the parsed manifest on success,
    or ok=False with a list of error messages on failure.
    """
    try:
        manifest = HireManifest(**raw)
        return HireValidation(ok=True, manifest=manifest)
    except ValidationError as e:
        errors = [err["msg"] for err in e.errors()]
        return HireValidation(ok=False, errors=errors)
    except (TypeError, ValueError) as e:
        return HireValidation(ok=False, errors=[str(e)])
