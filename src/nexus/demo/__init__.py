"""NEXUS Demo Configuration - company bootstrapping and scenario execution.

Provides demo configuration for NexusCorp, a sample AI company
with a full organizational hierarchy, budget policies, approval gates,
and ready-to-run scenarios demonstrating the delegation chain.

Exports:
    setup_demo_company: Idempotent bootstrapper for the demo company.
    SCENARIOS: List of pre-defined demo scenario configurations.
"""

from nexus.demo.scenarios import SCENARIOS
from nexus.demo.setup import setup_demo_company

__all__ = [
    "setup_demo_company",
    "SCENARIOS",
]
