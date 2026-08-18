"""NEXUS SQLModel table definitions.

All models are imported here so Alembic can discover them for migration autogeneration.
"""

from nexus.models.agent import Agent
from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.models.communication import Event, Group, GroupMember, Message
from nexus.models.company import Company, CompanyMembership, Department, Team
from nexus.models.evolution import (
    AgentVersion,
    EvolutionEvaluation,
    EvolutionProposal,
    SkillVersion,
)
from nexus.models.governance import Approval, AuditLog, Decision, DecisionQueue
from nexus.models.incident import Incident, IncidentAction, IncidentEvent
from nexus.models.knowledge import ExperienceRecord, KnowledgeChunk, KnowledgePage
from nexus.models.meeting import ActionItem, Meeting, MeetingMinutes, MeetingParticipant
from nexus.models.memory import MemoryRecord
from nexus.models.policy import Policy, PolicyRule, PolicyVersion
from nexus.models.secret import Secret, SecretAccess, SecretBinding, SecretVersion
from nexus.models.skill import AgentSkill, Skill
from nexus.models.task import Goal, Project, Task
from nexus.models.tool import Tool, ToolAccess
from nexus.models.trigger import Trigger, TriggerExecution
from nexus.governance.kill_switch_model import KillSwitchRecord
from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

__all__ = [
    # Company / Organization
    "Company",
    "CompanyMembership",
    "Department",
    "Team",
    # Agents
    "Agent",
    # Work Management
    "Goal",
    "Project",
    "Task",
    # Budget
    "BudgetPolicy",
    "CostEvent",
    # Governance
    "Approval",
    "Decision",
    "DecisionQueue",
    "AuditLog",
    # Policies
    "Policy",
    "PolicyRule",
    "PolicyVersion",
    # Secrets
    "Secret",
    "SecretVersion",
    "SecretBinding",
    "SecretAccess",
    # Incidents
    "Incident",
    "IncidentEvent",
    "IncidentAction",
    # Skills
    "Skill",
    "AgentSkill",
    # Tools
    "Tool",
    "ToolAccess",
    # Memory
    "MemoryRecord",
    # Triggers
    "Trigger",
    "TriggerExecution",
    # Communication
    "Message",
    "Group",
    "GroupMember",
    "Event",
    # Knowledge
    "KnowledgePage",
    "KnowledgeChunk",
    "ExperienceRecord",
    # Meetings
    "Meeting",
    "MeetingParticipant",
    "MeetingMinutes",
    "ActionItem",
    # Evolution
    "EvolutionProposal",
    "EvolutionEvaluation",
    "SkillVersion",
    "AgentVersion",
    # Governance persistence
    "KillSwitchRecord",
    "CircuitBreakerRecord",
]
