"""NEXUS SQLModel table definitions.

All models are imported here so Alembic can discover them for migration autogeneration.
"""

from nexus.models.agent import Agent
from nexus.models.auth import Invite
from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.models.chat import ChatMessage
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
from nexus.models.tool import (
    Tool,
    ToolAccess,
    ToolCatalogEntry,
    ToolConnection,
    ToolPolicy,
    ToolProfile,
    ToolProfileBinding,
)
from nexus.models.tool_invocation import ToolInvocation
from nexus.models.trigger import Trigger, TriggerExecution
from nexus.governance.kill_switch_model import KillSwitchRecord
from nexus.governance.circuit_breaker_model import CircuitBreakerRecord
from nexus.models.api_key import ApiKey
from nexus.models.user_profile import UserProfile, UserSession
from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime.checkpoint import ExecutionCheckpoint

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
    "ToolConnection",
    "ToolCatalogEntry",
    "ToolProfile",
    "ToolProfileBinding",
    "ToolPolicy",
    "ToolInvocation",
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
    # Runtime persistence
    "ExecutionCheckpoint",
    "HeartbeatRun",
    # Authentication / authorization
    "UserProfile",
    "UserSession",
    "Invite",
    "ApiKey",
    # Chat
    "ChatMessage",
]
