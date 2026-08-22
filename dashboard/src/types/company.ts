import type { UUID, DateTimeString, CompanyStatus, BudgetScopeType, BudgetMetric, BudgetWindowKind, ApprovalStatus } from './common';

export interface Company {
  id: UUID;
  name: string;
  description: string;
  status: CompanyStatus;
  budget_monthly_cents: number;
  spent_monthly_cents: number;
  issue_prefix: string;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface CompanyCreateRequest {
  name: string;
  description?: string;
  budget_monthly_cents?: number;
  issue_prefix?: string;
  status?: CompanyStatus;
}

export interface BudgetPolicy {
  id: UUID;
  company_id: UUID;
  scope_type: BudgetScopeType;
  scope_id: UUID;
  metric: BudgetMetric;
  window_kind: BudgetWindowKind;
  amount: number;
  warn_percent: number;
  hard_stop_enabled: boolean;
  is_active: boolean;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface BudgetUsage {
  scope_type: BudgetScopeType;
  scope_id: UUID;
  total_cost_cents: number;
  total_input_tokens: number;
  total_output_tokens: number;
  event_count: number;
}

export interface Approval {
  id: UUID;
  company_id: UUID;
  type: string;
  requested_by_agent_id: UUID;
  status: ApprovalStatus;
  payload: Record<string, unknown>;
  decision_note: string | null;
  decided_by: string | null;
  expires_at: DateTimeString | null;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface ApprovalDecisionRequest {
  status: 'approved' | 'rejected';
  decision_note?: string;
  decided_by: string;
}
