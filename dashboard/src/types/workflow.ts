export interface DAGStep {
  step_id: string;
  step_name: string;
  agent_role: string;
  agent_name?: string;
  action: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  cost_cents?: number;
  logs?: string;
  output_payload?: string;
}

export interface WorkflowDAGItem {
  workflow_id: string;
  title?: string;
  objective: string;
  template_type?: 'Feature Implementation' | 'Security Remediation' | 'Refactoring & AST' | 'Custom DAG';
  status: 'running' | 'completed' | 'failed' | 'paused';
  current_step: string;
  total_steps: number;
  completed_steps: number;
  total_cost_cents: number;
  duration_ms?: number;
  started_at: string;
  completed_at?: string | null;
  steps: DAGStep[];
}
