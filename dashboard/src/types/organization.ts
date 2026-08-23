export interface Department {
  id: string;
  name: string;
  code: string;
  head_agent_id: string;
  head_agent_name: string;
  head_agent_role: string;
  description: string;
  monthly_budget_cents: number;
  spent_cents: number;
  squad_count: number;
  agent_count: number;
  color: string;
  created_at: string;
  updated_at: string;
}

export interface Squad {
  id: string;
  department_id: string;
  department_name: string;
  name: string;
  lead_agent_id: string;
  lead_agent_name: string;
  lead_role: string;
  description: string;
  agent_ids: string[];
  color: string;
  active_tasks_count: number;
  ast_coverage: number;
  health_status: 'healthy' | 'degraded' | 'critical';
  created_at: string;
}

export interface OrgNode {
  id: string;
  name: string;
  title: string;
  role: string;
  type: 'executive' | 'department_head' | 'squad_lead' | 'worker';
  status: 'active' | 'idle' | 'busy' | 'offline';
  performance_score: number;
  department_id?: string;
  squad_id?: string;
  reports_to?: string;
  children?: OrgNode[];
}
