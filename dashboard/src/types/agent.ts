import type { AgentStatus, DateTimeString, UUID } from './common';

export interface Agent {
  id: UUID;
  company_id: UUID;
  name: string;
  title: string;
  role: string;
  department_id: UUID | null;
  team_id: UUID | null;
  manager_id: UUID | null;
  status: AgentStatus;
  adapter_type: string;
  /** Resolved CLI backend ID, or null for non-CLI adapters. */
  cli_backend?: string | null;
  model: string;
  capabilities: string[];
  responsibilities: string;
  objectives: string;
  budget_monthly_cents: number;
  spent_monthly_cents: number;
  performance_score?: number;
  soul_description: string;
  /** Per-action autonomy policy: { action_type: 1|2|3, spend_above_cents?: number }. */
  autonomy_policy?: Record<string, number> | null;
  last_heartbeat_at: DateTimeString | null;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}

export interface AgentCreateRequest {
  name: string;
  title: string;
  role: string;
  department_id?: UUID;
  team_id?: UUID;
  manager_id?: UUID;
  adapter_type: string;
  /** Canonical CLI config when adapter_type is "cli". */
  adapter_config?: { backend: string; interactive: false; use_worktree: false; autonomy_mode: 'safe'; extra_args: string[] };
  /** Hire into status configuration_required when the backend is not usable yet. */
  allow_unavailable_backend?: boolean;
  model: string;
  capabilities?: string[];
  responsibilities?: string;
  objectives?: string;
  budget_monthly_cents?: number;
  soul_description?: string;
}

export interface AgentUpdateRequest {
  name?: string;
  title?: string;
  role?: string;
  department_id?: UUID | null;
  team_id?: UUID | null;
  manager_id?: UUID | null;
  status?: AgentStatus;
  adapter_type?: string;
  model?: string;
  capabilities?: string[];
  responsibilities?: string;
  objectives?: string;
  budget_monthly_cents?: number;
  soul_description?: string;
}

export interface MemoryEntry {
  id: UUID;
  company_id: UUID;
  agent_id: UUID | null;
  scope: string;
  scope_id: UUID | null;
  content: string;
  metadata: Record<string, unknown>;
  importance: number;
  access_count: number;
  tier: string;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}
