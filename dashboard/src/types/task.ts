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
  'verification_failed',
  'cancelled',
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
  verification_failed: 'Verification failed',
  cancelled: 'Cancelled',
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
  /** Set for work tasks: only a verified attempt can complete them. */
  work_spec?: Record<string, unknown> | null;
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

export type AttemptStatus =
  | 'queued'
  | 'claimed'
  | 'running'
  | 'verifying'
  | 'completed'
  | 'failed'
  | 'blocked'
  | 'cancelled'
  | 'expired';

/** The employee's structured report, as the server validated and stored it. */
export interface EmployeeReport {
  state: 'working' | 'blocked' | 'verifying' | 'completed' | 'failed';
  summary?: string;
  progress_percent?: number | null;
  current_step?: string | null;
  completed_steps?: string[];
  next_step?: string | null;
  blockers?: string[];
  artifacts?: string[];
  tests_run?: string[];
  confidence?: number | null;
  needs_help?: boolean;
  eta?: string | null;
  seq?: number;
  source?: 'progress' | 'final';
}

export interface ArtifactEntry {
  path: string;
  type: string;
  size: number;
  sha256: string;
  commit?: string | null;
  deliverable?: boolean;
  validation: string;
}

export interface VerificationCommand {
  id: string;
  command: string;
  argv: string[];
  exit_code: number | null;
  timed_out: boolean;
  passed: boolean;
  tests?: Record<string, number> | null;
}

export interface TaskAttempt {
  id: UUID;
  task_id: UUID;
  agent_id: UUID;
  session_id?: UUID | null;
  attempt_number: number;
  status: AttemptStatus;
  active: boolean;
  execution_id?: string | null;
  cancel_requested: boolean;
  completion_reason?: CompletionReason | null;
  error_code?: string | null;
  error?: string | null;
  report?: EmployeeReport | null;
  report_seq: number;
  artifacts: ArtifactEntry[];
  verification?: {
    passed: boolean;
    error_code?: string | null;
    commands: VerificationCommand[];
  } | null;
  usage?: { backend?: string | null; model?: string | null } | null;
  updated_at?: DateTimeString | null;
}
