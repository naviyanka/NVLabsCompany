"""Temporal Workflow Integration for NEXUS.

Provides durable workflow execution via Temporal. When TEMPORAL_ENABLED=true
and a Temporal server is reachable, workflows run durably (survive crashes).
Otherwise, falls back to the existing BackgroundTasks implementation.

Components:
- activities.py: @activity.defn wrappers for LLM calls, task routing, etc.
- workflows.py: @workflow.defn for GoalPursuit, Pipeline execution
- worker.py: Worker process that polls Temporal for work
- client.py: Starts workflows from API routes
"""
