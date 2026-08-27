import type { UUID, DateTimeString, TaskStatus, TaskPriority } from './common';

/** Why a run reached a terminal state — mirrors nexus.models.task.RunCompletionReason. */
export const COMPLETION_REASONS = [
  'goal',
  'no_tool_calls',
  'max_iterations',
  'timeout',
  'budget_exhausted',
  'doom_loop',
  'needs_help',
  'error',
] as const;

export type CompletionReason = (typeof COMPLETION_REASONS)[number];

/** Short human labels for the filter chips. */
export const COMPLETION_REASON_LABELS: Record<CompletionReason, string> = {
  goal: 'Goal met',
  no_tool_calls: 'No output',
  max_iterations: 'Max iterations',
  timeout: 'Timed out',
  budget_exhausted: 'Budget out',
  doom_loop: 'Doom loop',
  needs_help: 'Needs help',
  error: 'Error',
};

export interface TaskSubtask {
  id: string;
  title: string;
  completed: boolean;
}

export interface Task {
  id: UUID;
  company_id: UUID;
  project_id?: string | null;
  title: string;
  description: string;
  status: TaskStatus;
  priority: TaskPriority;
  assigned_agent_id?: UUID | null;
  parent_task_id?: UUID | null;
  result?: string | null;
  error?: string | null;
  completion_reason?: CompletionReason | null;
  logs?: string | null;
  cost_cents?: number | null;
  subtasks?: TaskSubtask[];
  started_at?: DateTimeString | null;
  completed_at?: DateTimeString | null;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface TaskCreateRequest {
  title: string;
  description?: string;
  priority?: TaskPriority;
  assigned_agent_id?: UUID | null;
  project_id?: string | null;
  subtasks?: TaskSubtask[];
}
