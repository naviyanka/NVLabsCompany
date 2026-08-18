import type { UUID, DateTimeString, TaskStatus } from './common';

export interface Task {
  id: UUID;
  company_id: UUID;
  project_id: UUID | null;
  title: string;
  description: string;
  status: TaskStatus;
  priority: number;
  assigned_agent_id: UUID | null;
  parent_task_id: UUID | null;
  result: string | null;
  error: string | null;
  started_at: DateTimeString | null;
  completed_at: DateTimeString | null;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface TaskCreateRequest {
  title: string;
  description: string;
  priority?: number;
  assigned_agent_id?: UUID;
  parent_task_id?: UUID;
  project_id?: UUID;
}

export interface TaskUpdateRequest {
  title?: string;
  description?: string;
  status?: TaskStatus;
  priority?: number;
  assigned_agent_id?: UUID | null;
  result?: string;
  error?: string;
}
