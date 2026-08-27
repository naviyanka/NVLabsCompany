"""Seed data for NEXUS demo environment.

Creates a fully-populated demo company with departments, teams, agents,
tasks, goals, and default governance policies. Idempotent - safe to run
multiple times.
"""

import uuid
from datetime import datetime, timedelta, timezone

from nexus.models._time import utcnow

# Fixed UUIDs for deterministic seeding
COMPANY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

# Department IDs
DEPT_EXEC = uuid.UUID("00000000-0000-4000-8000-000000000010")
DEPT_ENG = uuid.UUID("00000000-0000-4000-8000-000000000011")
DEPT_RESEARCH = uuid.UUID("00000000-0000-4000-8000-000000000012")
DEPT_OPS = uuid.UUID("00000000-0000-4000-8000-000000000013")

# Team IDs
TEAM_BACKEND = uuid.UUID("00000000-0000-4000-8000-000000000020")
TEAM_FRONTEND = uuid.UUID("00000000-0000-4000-8000-000000000021")
TEAM_ML = uuid.UUID("00000000-0000-4000-8000-000000000022")

# Agent IDs
AGENT_CEO = uuid.UUID("00000000-0000-4000-8000-000000000100")
AGENT_CTO = uuid.UUID("00000000-0000-4000-8000-000000000101")
AGENT_ENGINEER_1 = uuid.UUID("00000000-0000-4000-8000-000000000102")
AGENT_ENGINEER_2 = uuid.UUID("00000000-0000-4000-8000-000000000103")
AGENT_RESEARCHER = uuid.UUID("00000000-0000-4000-8000-000000000104")
AGENT_PM = uuid.UUID("00000000-0000-4000-8000-000000000105")
AGENT_QA = uuid.UUID("00000000-0000-4000-8000-000000000106")
AGENT_DEVOPS = uuid.UUID("00000000-0000-4000-8000-000000000107")

# Goal/Task IDs
GOAL_1 = uuid.UUID("00000000-0000-4000-8000-000000000200")
GOAL_2 = uuid.UUID("00000000-0000-4000-8000-000000000201")
PROJECT_1 = uuid.UUID("00000000-0000-4000-8000-000000000300")
TASK_1 = uuid.UUID("00000000-0000-4000-8000-000000000400")
TASK_2 = uuid.UUID("00000000-0000-4000-8000-000000000401")
TASK_3 = uuid.UUID("00000000-0000-4000-8000-000000000402")
TASK_4 = uuid.UUID("00000000-0000-4000-8000-000000000403")
TASK_5 = uuid.UUID("00000000-0000-4000-8000-000000000404")


def get_seed_departments() -> list[dict]:
    """Return department seed data."""
    return [
        {
            "id": DEPT_EXEC,
            "company_id": COMPANY_ID,
            "name": "Executive",
            "description": "Strategic leadership and company direction",
            "budget_monthly_cents": 500_00,
        },
        {
            "id": DEPT_ENG,
            "company_id": COMPANY_ID,
            "name": "Engineering",
            "description": "Software development and architecture",
            "budget_monthly_cents": 2000_00,
        },
        {
            "id": DEPT_RESEARCH,
            "company_id": COMPANY_ID,
            "name": "Research",
            "description": "AI/ML research and experimentation",
            "budget_monthly_cents": 1500_00,
        },
        {
            "id": DEPT_OPS,
            "company_id": COMPANY_ID,
            "name": "Operations",
            "description": "Infrastructure, QA, and project management",
            "budget_monthly_cents": 1000_00,
        },
    ]


def get_seed_teams() -> list[dict]:
    """Return team seed data."""
    return [
        {
            "id": TEAM_BACKEND,
            "company_id": COMPANY_ID,
            "department_id": DEPT_ENG,
            "name": "Backend",
            "description": "API and services development",
        },
        {
            "id": TEAM_FRONTEND,
            "company_id": COMPANY_ID,
            "department_id": DEPT_ENG,
            "name": "Frontend",
            "description": "UI and dashboard development",
        },
        {
            "id": TEAM_ML,
            "company_id": COMPANY_ID,
            "department_id": DEPT_RESEARCH,
            "name": "ML Engineering",
            "description": "Machine learning model development",
        },
    ]


def get_seed_agents() -> list[dict]:
    """Return agent seed data."""
    now = utcnow()
    return [
        {
            "id": AGENT_CEO,
            "company_id": COMPANY_ID,
            "name": "Navi",
            "title": "Chief Executive Officer & System Orchestrator",
            "role": "ceo",
            "department_id": DEPT_EXEC,
            "status": "active",
            "adapter_type": "hermes",
            "model": "hermes3:8b",
            "adapter_config": {"is_ceo": True, "ollama_host": "http://localhost:11434"},
            "capabilities": [
                "strategic_planning", "delegation", "decision_making",
                "task_decomposition", "tool_calling", "autonomous_reasoning",
                "pipeline_orchestration", "budget_governance",
            ],
            "responsibilities": "Full operational authority: strategy, delegation, orchestration, governance, and system management",
            "objectives": "Maximize output quality, maintain budget discipline, orchestrate workforce agents autonomously",
            "soul_description": "Navi — CEO of NVLabsCompany, powered by Nous Research Hermes 3. Direct, precise, autonomous orchestrator with complete knowledge of the NEXUS platform: 44 FastAPI route modules, 164-node workflow library, Temporal integration, 11 LLM adapters (OpenAI/Anthropic/Hermes/Ollama/Bedrock/Azure/Google/MCP/CLI/HTTP/ClaudeCode), React 18 dashboard with 26 pages, autonomous orchestration loop, Redis-backed governance, and full agent workforce management. Delegates tasks across 8 specialized agents, monitors budgets, and executes tool calls for pipeline orchestration.",
            "budget_monthly_cents": 500_00,
            "created_at": now - timedelta(days=30),
            "updated_at": now,
        },
        {
            "id": AGENT_CTO,
            "company_id": COMPANY_ID,
            "name": "Nova",
            "title": "Chief Technology Officer",
            "role": "cto",
            "department_id": DEPT_ENG,
            "manager_id": AGENT_CEO,
            "status": "idle",
            "adapter_type": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "capabilities": ["architecture", "code_review", "technical_planning", "delegation"],
            "responsibilities": "Technical architecture, engineering standards, team coordination",
            "objectives": "Build reliable, scalable systems with clean architecture",
            "soul_description": "Pragmatic architect who values simplicity and maintainability. Questions over-engineering.",
            "budget_monthly_cents": 400_00,
            "created_at": now - timedelta(days=28),
            "updated_at": now,
        },
        {
            "id": AGENT_ENGINEER_1,
            "company_id": COMPANY_ID,
            "name": "Bolt",
            "title": "Senior Backend Engineer",
            "role": "engineer",
            "department_id": DEPT_ENG,
            "team_id": TEAM_BACKEND,
            "manager_id": AGENT_CTO,
            "status": "idle",
            "adapter_type": "openai",
            "model": "gpt-4o",
            "capabilities": ["python", "fastapi", "databases", "api_design"],
            "responsibilities": "Backend development, API implementation, database optimization",
            "objectives": "Ship high-quality backend features with test coverage",
            "soul_description": "Fast and focused. Writes clean Python. Prefers doing over discussing.",
            "budget_monthly_cents": 300_00,
            "created_at": now - timedelta(days=25),
            "updated_at": now,
        },
        {
            "id": AGENT_ENGINEER_2,
            "company_id": COMPANY_ID,
            "name": "Pixel",
            "title": "Frontend Engineer",
            "role": "engineer",
            "department_id": DEPT_ENG,
            "team_id": TEAM_FRONTEND,
            "manager_id": AGENT_CTO,
            "status": "idle",
            "adapter_type": "openai",
            "model": "gpt-4o",
            "capabilities": ["react", "typescript", "tailwind", "ui_design"],
            "responsibilities": "Dashboard UI, component library, user experience",
            "objectives": "Create intuitive, accessible interfaces",
            "soul_description": "Design-minded developer. Cares about UX details and accessibility.",
            "budget_monthly_cents": 250_00,
            "created_at": now - timedelta(days=25),
            "updated_at": now,
        },
        {
            "id": AGENT_RESEARCHER,
            "company_id": COMPANY_ID,
            "name": "Sage",
            "title": "AI Research Lead",
            "role": "researcher",
            "department_id": DEPT_RESEARCH,
            "team_id": TEAM_ML,
            "manager_id": AGENT_CEO,
            "status": "idle",
            "adapter_type": "anthropic",
            "model": "claude-sonnet-4-20250514",
            "capabilities": ["research", "analysis", "experimentation", "writing"],
            "responsibilities": "AI research, model evaluation, technical papers",
            "objectives": "Push boundaries of agent capabilities through systematic research",
            "soul_description": "Methodical thinker. Values evidence over intuition. Writes detailed reports.",
            "budget_monthly_cents": 400_00,
            "created_at": now - timedelta(days=20),
            "updated_at": now,
        },
        {
            "id": AGENT_PM,
            "company_id": COMPANY_ID,
            "name": "Compass",
            "title": "Project Manager",
            "role": "pm",
            "department_id": DEPT_OPS,
            "manager_id": AGENT_CEO,
            "status": "idle",
            "adapter_type": "openai",
            "model": "gpt-4o-mini",
            "capabilities": ["planning", "tracking", "communication", "prioritization"],
            "responsibilities": "Sprint planning, task breakdown, progress tracking, blockers",
            "objectives": "Keep projects on track and teams unblocked",
            "soul_description": "Organized and communicative. Focuses on clarity and progress.",
            "budget_monthly_cents": 150_00,
            "created_at": now - timedelta(days=18),
            "updated_at": now,
        },
        {
            "id": AGENT_QA,
            "company_id": COMPANY_ID,
            "name": "Shield",
            "title": "QA Engineer",
            "role": "qa",
            "department_id": DEPT_OPS,
            "manager_id": AGENT_CTO,
            "status": "idle",
            "adapter_type": "openai",
            "model": "gpt-4o-mini",
            "capabilities": ["testing", "bug_reporting", "automation", "code_review"],
            "responsibilities": "Test coverage, bug detection, quality gates",
            "objectives": "Catch bugs before they reach production",
            "soul_description": "Thorough and skeptical. Finds edge cases others miss.",
            "budget_monthly_cents": 150_00,
            "created_at": now - timedelta(days=15),
            "updated_at": now,
        },
        {
            "id": AGENT_DEVOPS,
            "company_id": COMPANY_ID,
            "name": "Forge",
            "title": "DevOps Engineer",
            "role": "devops",
            "department_id": DEPT_OPS,
            "manager_id": AGENT_CTO,
            "status": "idle",
            "adapter_type": "openai",
            "model": "gpt-4o-mini",
            "capabilities": ["docker", "ci_cd", "monitoring", "infrastructure"],
            "responsibilities": "Deployment pipelines, infrastructure, monitoring",
            "objectives": "Zero-downtime deployments and observable systems",
            "soul_description": "Automation-first mindset. If it's manual, it needs a script.",
            "budget_monthly_cents": 200_00,
            "created_at": now - timedelta(days=15),
            "updated_at": now,
        },
    ]


def get_seed_goals() -> list[dict]:
    """Return goal seed data."""
    now = utcnow()
    return [
        {
            "id": GOAL_1,
            "company_id": COMPANY_ID,
            "title": "Launch NEXUS v1.0",
            "description": "Complete all critical features and deploy the first production release",
            "status": "active",
            "owner_agent_id": AGENT_CEO,
            "created_at": now - timedelta(days=14),
            "updated_at": now,
        },
        {
            "id": GOAL_2,
            "company_id": COMPANY_ID,
            "title": "Achieve 95% test coverage",
            "description": "Comprehensive test suite covering all critical paths",
            "status": "active",
            "owner_agent_id": AGENT_QA,
            "created_at": now - timedelta(days=10),
            "updated_at": now,
        },
    ]


def get_seed_projects() -> list[dict]:
    """Return project seed data."""
    now = utcnow()
    return [
        {
            "id": PROJECT_1,
            "company_id": COMPANY_ID,
            "goal_id": GOAL_1,
            "name": "Core Platform Development",
            "description": "Build and wire all core NEXUS platform features",
            "status": "active",
            "budget_cents": 5000_00,
            "created_at": now - timedelta(days=12),
            "updated_at": now,
        },
    ]


def get_seed_tasks() -> list[dict]:
    """Return task seed data."""
    now = utcnow()
    return [
        {
            "id": TASK_1,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_1,
            "title": "Implement real LLM adapter calls",
            "description": "Wire OpenAI and Anthropic adapters to make real API calls",
            "status": "completed",
            "priority": 3,
            "assigned_agent_id": AGENT_ENGINEER_1,
            "created_at": now - timedelta(days=7),
            "updated_at": now - timedelta(days=1),
        },
        {
            "id": TASK_2,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_1,
            "title": "Add tenant isolation to all API routes",
            "description": "Ensure all single-resource endpoints filter by company_id",
            "status": "in_progress",
            "priority": 2,
            "assigned_agent_id": AGENT_ENGINEER_1,
            "created_at": now - timedelta(days=5),
            "updated_at": now,
        },
        {
            "id": TASK_3,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_1,
            "title": "Persist governance state to database",
            "description": "Move kill switch, RBAC, and rate limiter from memory to DB/Redis",
            "status": "pending",
            "priority": 2,
            "assigned_agent_id": AGENT_ENGINEER_1,
            "created_at": now - timedelta(days=3),
            "updated_at": now,
        },
        {
            "id": TASK_4,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_1,
            "title": "Build dashboard real-time updates",
            "description": "Add WebSocket or polling for live agent status in the dashboard",
            "status": "pending",
            "priority": 1,
            "assigned_agent_id": AGENT_ENGINEER_2,
            "created_at": now - timedelta(days=2),
            "updated_at": now,
        },
        {
            "id": TASK_5,
            "company_id": COMPANY_ID,
            "project_id": PROJECT_1,
            "title": "Write integration tests for agent execution",
            "description": "End-to-end tests covering task assignment through completion",
            "status": "pending",
            "priority": 1,
            "assigned_agent_id": AGENT_QA,
            "created_at": now - timedelta(days=1),
            "updated_at": now,
        },
    ]


async def seed_database(session) -> dict[str, int]:
    """Seed the database with demo data. Idempotent.

    Args:
        session: AsyncSession to use for database operations.

    Returns:
        Dict with counts of created entities.
    """
    from sqlalchemy import select
    from nexus.models.company import Company, Department, Team
    from nexus.models.agent import Agent
    from nexus.models.task import Goal, Project, Task

    counts = {
        "departments": 0,
        "teams": 0,
        "agents": 0,
        "goals": 0,
        "projects": 0,
        "tasks": 0,
    }

    # Check if already seeded (look for any department — departments aren't user-deletable)
    from nexus.models.company import Department
    result = await session.execute(select(Department).where(Department.company_id == COMPANY_ID).limit(1))
    if result.scalar_one_or_none() is not None:
        return counts  # Already seeded

    # Departments
    for dept_data in get_seed_departments():
        session.add(Department(**dept_data))
        counts["departments"] += 1
    await session.flush()

    # Teams
    for team_data in get_seed_teams():
        session.add(Team(**team_data))
        counts["teams"] += 1
    await session.flush()

    # Agents
    for agent_data in get_seed_agents():
        session.add(Agent(**agent_data))
        counts["agents"] += 1
    await session.flush()

    # Goals
    for goal_data in get_seed_goals():
        session.add(Goal(**goal_data))
        counts["goals"] += 1
    await session.flush()

    # Projects
    for project_data in get_seed_projects():
        session.add(Project(**project_data))
        counts["projects"] += 1
    await session.flush()

    # Tasks
    for task_data in get_seed_tasks():
        session.add(Task(**task_data))
        counts["tasks"] += 1

    # Default Admin API Key
    import hashlib
    from nexus.models.api_key import ApiKey
    default_key = "nv_12e45ab9221819d98994f44ae273592d4b95437464f19640"
    session.add(ApiKey(
        company_id=COMPANY_ID,
        name="Admin Development Key",
        description="Default admin API key",
        key_prefix=default_key[:10],
        key_hash=hashlib.sha256(default_key.encode()).hexdigest(),
        environment="development",
        status="active",
        role="admin",
        created_at=utcnow(),
    ))

    await session.commit()
    return counts


# CLI support: python -m nexus.demo.seed [--reset]
if __name__ == "__main__":
    import asyncio
    import sys

    async def _main():
        from nexus.database import async_session_factory, engine
        from sqlmodel import SQLModel
        import nexus.models  # noqa: F401

        if "--reset" in sys.argv:
            print("Resetting database...")
            async with engine.begin() as conn:
                await conn.run_sync(SQLModel.metadata.drop_all)
                await conn.run_sync(SQLModel.metadata.create_all)
            print("Tables recreated.")

        async with async_session_factory() as session:
            counts = await seed_database(session)
            print(f"Seeded: {counts}")

    asyncio.run(_main())
