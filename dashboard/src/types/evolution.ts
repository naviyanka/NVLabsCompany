import type { UUID, DateTimeString, ProposalStatus, WorkflowStatus } from './common';

export interface Proposal {
  id: UUID;
  company_id: UUID;
  proposal_type: string;
  title: string;
  description: string;
  expected_impact: string;
  confidence: number;
  risk_level: string;
  estimated_cost_cents: number;
  status: ProposalStatus;
  proposed_by_agent_id: UUID;
  approved_by: string | null;
  approval_id: UUID | null;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface Evaluation {
  id: UUID;
  proposal_id: UUID;
  company_id: UUID;
  baseline_score: number;
  candidate_score: number;
  improvement_percent: number;
  statistical_significance: number;
  dimensions: Record<string, unknown>;
  passed: boolean;
  evaluated_at: DateTimeString;
}

export interface WorkflowStatusResponse {
  workflow_id: string;
  status: WorkflowStatus;
  objective: string;
  current_step: string;
  total_cost_cents: number;
  started_at: DateTimeString;
  completed_at: DateTimeString | null;
}

export interface WorkflowStep {
  step_id: string;
  agent_role: string;
  action: string;
  status: WorkflowStatus;
  cost_cents: number;
  started_at: DateTimeString;
  completed_at: DateTimeString | null;
  error: string | null;
}
