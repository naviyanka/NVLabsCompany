/**
 * Agents API module — dedicated endpoints for agent CRUD, hiring, archetypes, and providers.
 */

import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { Agent, AgentCreateRequest } from '@/types/agent';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface AgentArchetype {
  name: string;
  role: string;
  capabilities: string[];
  constraints: string[];
  system_prompt: string;
  tools_allowed: string[];
  interaction_style: string;
  description: string;
}

/** One CLI backend from the server catalog (`nexus.adapters.cli_registry`). */
export interface AgentProvider {
  id: string;
  label: string;
  adapter_type: 'cli';
  installed: boolean;
  resolved_command: string | null;
  version: string | null;
  execution_supported: boolean;
  /** true/false when the server can tell; null means unknown. */
  configured: boolean | null;
  stability: 'stable' | 'beta' | 'experimental';
  supports_model: boolean;
  supports_resume: boolean;
  supports_interactive: boolean;
  supports_worktree: boolean;
  instruction_path?: string | null;
  recommended_model: string | null;
  models: string[];
  install_command: string | null;
  docs_url: string | null;
  notes: string | null;
}

export interface ProviderProbe {
  id: string;
  installed: boolean;
  resolved_command: string | null;
  version: string | null;
  execution_supported: boolean;
  configured: boolean | null;
  ok: boolean;
  error: string | null;
}

/** Canonical adapter_config for a CLI employee. Never carries paths or secrets. */
export interface CliAdapterConfig {
  backend: string;
  interactive: false;
  use_worktree: false;
  autonomy_mode: 'safe';
  extra_args: string[];
}

export function cliAdapterConfig(backend: string): CliAdapterConfig {
  return { backend, interactive: false, use_worktree: false, autonomy_mode: 'safe', extra_args: [] };
}

export interface AgentTemplate {
  name: string;
  description: string;
  file_path: string;
}

export interface TeamAgentSpec {
  name: string;
  archetype?: string;
  role?: string;
  title?: string;
  model?: string;
  adapter_type?: string;
  adapter_config?: CliAdapterConfig;
  capabilities?: string[];
  responsibilities?: string;
  objectives?: string;
  soul_description?: string;
  budget_monthly_cents?: number;
}

export interface HireTeamRequest {
  team_name: string;
  department_id?: string;
  manager_id?: string;
  agents: TeamAgentSpec[];
}

export interface HireTeamResponse {
  team_name: string;
  department_id: string | null;
  agents_created: number;
  agents: Array<{
    id: string;
    name: string;
    role: string;
    title: string | null;
    model: string | null;
    status: string;
    capabilities: string[] | null;
  }>;
}

export interface HireFromManifestRequest {
  manifest: Record<string, unknown>;
  name_override?: string;
  department_id?: string;
  team_id?: string;
  manager_id?: string;
  budget_monthly_cents?: number;
}

// ---------------------------------------------------------------------------
// API Functions
// ---------------------------------------------------------------------------

function companyPath(path: string): string {
  return `/api/v1/companies/${getActiveCompanyId()}${path}`;
}

/** List all agents for the active company. */
export async function listAgents(): Promise<Agent[]> {
  return apiClient.get<Agent[]>(companyPath('/agents'));
}

/** Create a single agent. */
export async function createAgent(body: AgentCreateRequest): Promise<Agent> {
  return apiClient.post<Agent>(companyPath('/agents'), body);
}

/** Batch-hire a team of agents. */
export async function hireTeam(body: HireTeamRequest): Promise<HireTeamResponse> {
  return apiClient.post<HireTeamResponse>(companyPath('/agents/hire-team'), body);
}

/** Hire an agent from a portable manifest JSON. */
export async function hireFromManifest(body: HireFromManifestRequest): Promise<Record<string, unknown>> {
  return apiClient.post<Record<string, unknown>>(companyPath('/agents/hire-from-manifest'), body);
}

/** List all 20 pre-built agent archetypes. */
export async function listArchetypes(): Promise<AgentArchetype[]> {
  return apiClient.get<AgentArchetype[]>('/api/v1/agent-archetypes');
}

/** List all cataloged CLI backends with detection status. */
export async function listProviders(): Promise<AgentProvider[]> {
  return apiClient.get<AgentProvider[]>('/api/v1/agent-providers');
}

/** Re-detect one backend (PATH + `--version`). Runs no LLM task. */
export async function probeProvider(backendId: string): Promise<ProviderProbe> {
  return apiClient.post<ProviderProbe>(`/api/v1/agent-providers/${encodeURIComponent(backendId)}/probe`);
}

/** List available agent role templates (markdown-based). */
export async function listTemplates(): Promise<AgentTemplate[]> {
  return apiClient.get<AgentTemplate[]>('/api/v1/agent-templates');
}

export interface TeamTemplateAgent {
  archetype: string;
  suggested_name: string;
  default_provider: string;
  default_model: string;
  reports_to_index: number;
  title_override: string;
}

export interface TeamTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  tags: string[];
  agent_count: number;
  agents: TeamTemplateAgent[];
}

/** List all pre-built team composition templates. */
export async function listTeamTemplates(): Promise<TeamTemplate[]> {
  return apiClient.get<TeamTemplate[]>('/api/v1/team-templates');
}

export interface SoulData {
  role: string;
  personality_traits: string[];
  communication_style: string;
  expertise: string[];
  values: string[];
  constraints: string[];
  background: string;
  tone: string;
}

export interface SoulTemplate {
  template_id: string;
  name: string;
  description: string;
  soul: SoulData;
}

/** List all soul templates with full personality configuration. */
export async function listSoulTemplates(): Promise<SoulTemplate[]> {
  return apiClient.get<SoulTemplate[]>('/api/v1/soul-templates');
}

/** Wake an agent (idle/paused → ready). */
export async function wakeAgent(agentId: string): Promise<Agent> {
  return apiClient.post<Agent>(`/api/v1/agents/${agentId}/wake`);
}

/** Pause an agent. */
export async function pauseAgent(agentId: string): Promise<Agent> {
  return apiClient.post<Agent>(`/api/v1/agents/${agentId}/pause`);
}

/** Delete an agent permanently. */
export async function deleteAgent(agentId: string): Promise<void> {
  return apiClient.delete<void>(`/api/v1/agents/${agentId}`);
}

export interface AgentUpdateRequest {
  name?: string;
  title?: string;
  role?: string;
  status?: string;
  adapter_type?: string;
  model?: string;
  capabilities?: string[];
  responsibilities?: string;
  objectives?: string;
  soul_description?: string;
  budget_monthly_cents?: number;
}

/** Update an existing agent's configuration and soul. */
export async function updateAgent(agentId: string, body: AgentUpdateRequest): Promise<Agent> {
  return apiClient.patch<Agent>(companyPath(`/agents/${agentId}`), body);
}
