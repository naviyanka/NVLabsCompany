"""Agent runtime layer: adapter interfaces, lifecycle, execution, and monitoring."""

from nexus.runtime.adapter import AgentAdapter, AgentSession, TaskResult
from nexus.runtime.lifecycle import AgentLifecycleManager
from nexus.runtime.executor import TaskExecutor
from nexus.runtime.checkpoint import (
    CheckpointManager,
    CheckpointStatus,
    DurableCheckpointService,
    ExecutionCheckpoint,
    abandon_stale,
    build_checkpoint_state,
    load_latest,
    mark_completed,
    resume_from_checkpoint,
    save_checkpoint,
    save_checkpoint_nonblocking,
)
from nexus.runtime.closing_time import ClosingTimeController, ClosingTimeEvent, ClosingTimePhase
from nexus.runtime.cycle_guard import CycleGuard, CycleGuardError
from nexus.runtime.heartbeat_persistent import PersistentHeartbeatService
from nexus.runtime.replay import ReplayEngine
from nexus.runtime.watchdog import Watchdog, WatchdogConfig
from nexus.runtime.worktree import WorktreeManager, WorktreeInfo, MergeResult

__all__ = [
    "AgentAdapter",
    "AgentSession",
    "TaskResult",
    "AgentLifecycleManager",
    "ClosingTimeController",
    "ClosingTimeEvent",
    "ClosingTimePhase",
    "TaskExecutor",
    "CheckpointManager",
    "CheckpointStatus",
    "DurableCheckpointService",
    "CycleGuard",
    "CycleGuardError",
    "ExecutionCheckpoint",
    "MergeResult",
    "PersistentHeartbeatService",
    "ReplayEngine",
    "Watchdog",
    "WatchdogConfig",
    "WorktreeInfo",
    "WorktreeManager",
    "abandon_stale",
    "build_checkpoint_state",
    "load_latest",
    "mark_completed",
    "resume_from_checkpoint",
    "save_checkpoint",
    "save_checkpoint_nonblocking",
]
