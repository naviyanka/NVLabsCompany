export interface KeyResult {
  id: string;
  title: string;
  target_value: number;
  current_value: number;
  unit: string;
  progress: number;
  status: 'not_started' | 'in_progress' | 'completed';
  owner_agent_name?: string;
}

export interface GoalItem {
  id: string;
  title: string;
  description: string;
  department_id?: string;
  department_name?: string;
  owner_agent_id?: string;
  owner_agent_name?: string;
  status: 'active' | 'in_progress' | 'completed' | 'paused';
  progress: number;
  target_date: string;
  quarter?: string;
  key_results?: KeyResult[];
  linked_task_ids?: string[];
  created_at?: string;
  updated_at?: string;
}
