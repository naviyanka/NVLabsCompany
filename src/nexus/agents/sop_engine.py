"""SOP Artifact Pipeline Engine — structured engineering output (from MetaGPT).

Generates standardized artifacts through a multi-stage pipeline:
1. PRD (Product Requirements Document)
2. Architecture Design (Mermaid diagram)
3. Implementation Plan (sequence diagram)
4. Code Generation
5. Test Cases

Each stage produces a structured artifact that feeds into the next,
ensuring engineering quality and traceability.
"""

from pathlib import Path
from typing import Any

_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Stage definitions for the SOP pipeline
SOP_STAGES = [
    {
        "name": "PRD Generation",
        "template": "prd.md",
        "output_type": "document",
        "prompt_prefix": "Generate a Product Requirements Document for the following task. Include: Problem Statement, User Stories, Success Metrics, Technical Requirements, Constraints.\n\nTask: ",
    },
    {
        "name": "Architecture Design",
        "template": "architecture.md",
        "output_type": "mermaid_diagram",
        "prompt_prefix": "Based on the following PRD, generate a system architecture design using Mermaid diagram syntax. Include component interactions, data flow, and API boundaries.\n\nPRD: ",
    },
    {
        "name": "Implementation Plan",
        "template": None,
        "output_type": "plan",
        "prompt_prefix": "Based on the architecture above, create a step-by-step implementation plan with file paths, function signatures, and dependencies.\n\nArchitecture: ",
    },
    {
        "name": "Code Generation",
        "template": None,
        "output_type": "code",
        "prompt_prefix": "Implement the following plan. Produce clean, well-documented code.\n\nPlan: ",
    },
    {
        "name": "Test Cases",
        "template": None,
        "output_type": "tests",
        "prompt_prefix": "Write comprehensive test cases for the implementation above. Include unit tests, integration tests, and edge cases.\n\nCode: ",
    },
]


def get_sop_stages() -> list[dict[str, Any]]:
    """Get the SOP pipeline stage definitions."""
    return SOP_STAGES


def build_sop_pipeline_stages(task_description: str) -> list[dict[str, Any]]:
    """Convert a task description into a pipeline with SOP stages.

    Returns a list of stage dicts compatible with the Pipeline model's
    `stages` JSON field, ready for execution by the pipeline runner.
    """
    stages = []
    for i, sop in enumerate(SOP_STAGES):
        stage: dict[str, Any] = {
            "name": sop["name"],
            "prompt": f"{sop['prompt_prefix']}{task_description}" if i == 0 else sop["prompt_prefix"],
            "quality_gate": i >= 3,  # Quality gate on code + tests
            "quality_threshold": 0.7,
        }
        stages.append(stage)
    return stages


def load_template(template_name: str) -> str | None:
    """Load a template file from the templates directory."""
    path = _TEMPLATES_DIR / template_name
    if path.exists():
        return path.read_text(encoding="utf-8")
    return None
