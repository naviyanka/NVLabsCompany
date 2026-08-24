export interface PipelineStage {
  id: string;
  name: string;
  assignedAgent: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration_ms?: number;
  logs?: string;
}

export interface PipelineRunHistory {
  run_id: string;
  pipeline_id: string;
  trigger_event: string;
  started_at: string;
  duration_ms: number;
  status: 'completed' | 'failed' | 'running';
  agent_count: number;
}

export interface PipelineItem {
  id: string;
  name: string;
  description?: string;
  status: 'idle' | 'running' | 'completed' | 'failed';
  success_rate: number;
  trigger: string;
  stages: PipelineStage[];
  last_run?: string;
  run_history?: PipelineRunHistory[];
  created_at?: string;
  canvas_nodes?: CanvasNode[];
  canvas_edges?: CanvasEdge[];
}

/* ── Visual Builder Types ── */

export interface CanvasNode {
  id: string;
  type: CanvasNodeType;
  label: string;
  x: number;
  y: number;
  agent?: string;
  config?: Record<string, string>;
}

export type CanvasNodeType =
  | 'trigger'
  | 'agent_task'
  | 'code_review'
  | 'security_gate'
  | 'test_suite'
  | 'deploy'
  | 'condition'
  | 'notification'
  | 'merge';

export interface CanvasEdge {
  id: string;
  from: string;      // source node id
  to: string;        // target node id
  label?: string;
}

export interface NodeTypeDefinition {
  type: CanvasNodeType;
  label: string;
  color: string;
  icon: string;   // emoji shorthand (rendered in SVG text)
  description: string;
  defaultAgent?: string;
}

export const NODE_TYPE_CATALOG: NodeTypeDefinition[] = [
  { type: 'trigger',       label: 'Trigger',         color: '#FFB020', icon: '⚡', description: 'Webhook, Cron, Git Push, or Manual dispatch', defaultAgent: 'System' },
  { type: 'agent_task',    label: 'Agent Task',       color: '#818CF8', icon: '🤖', description: 'Assign a task to a specific agent', defaultAgent: 'Atlas-01' },
  { type: 'code_review',   label: 'Code Review',      color: '#22D3EE', icon: '🔍', description: 'Automated code review & lint analysis', defaultAgent: 'Nova-02' },
  { type: 'security_gate', label: 'Security Gate',     color: '#22C55E', icon: '🛡️', description: 'gVisor sandbox audit & SAST scan', defaultAgent: 'Sentinel-07' },
  { type: 'test_suite',    label: 'Test Suite',        color: '#F472B6', icon: '🧪', description: 'Run unit, integration, or E2E tests', defaultAgent: 'Bolt-03' },
  { type: 'deploy',        label: 'Deploy',            color: '#FB923C', icon: '🚀', description: 'Canary rollout or production deploy', defaultAgent: 'Forge-04' },
  { type: 'condition',     label: 'Condition',         color: '#FACC15', icon: '⑂',  description: 'Branch pipeline based on a condition' },
  { type: 'notification',  label: 'Notification',      color: '#A78BFA', icon: '🔔', description: 'Send Slack, email, or webhook notification' },
  { type: 'merge',         label: 'Merge / Join',      color: '#94A3B8', icon: '⊕',  description: 'Wait for multiple upstream branches' },
];
