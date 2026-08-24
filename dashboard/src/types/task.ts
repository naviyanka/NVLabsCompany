import type { UUID, DateTimeString, TaskStatus, TaskPriority } from './common';

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
