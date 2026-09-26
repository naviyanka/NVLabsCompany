/**
 * Canvas API module — the domain reads and mutations the Canvas draws from.
 *
 * The Canvas keeps no graph of its own: every node and edge is a projection of
 * a row returned here (agents, reporting lines, bindings, tools, pipelines),
 * and every change is one of these calls. Whether a tool is usable comes only
 * from the server's effective-tools answer.
 */

import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { EffectiveTool, McpBinding } from '@/api/sessions';

export interface Department {
  id: string;
  name: string;
  description: string | null;
}

export interface Team {
  id: string;
  name: string;
  description: string | null;
  department_id: string;
}

export interface Delegation {
  id: string;
  task_id: string;
  from_agent_id: string;
  to_agent_id: string;
  reason: string | null;
  created_at: string;
}

export interface ToolConnection {
  id: string;
  name: string;
  transport_type: string;
  health_status: string;
  is_active: boolean;
}

export interface CatalogTool {
  id: string;
  connection_id: string;
  tool_name: string;
  description: string | null;
  risk_level: string;
  is_active: boolean;
}

/** A pipeline as the backend stores it: ordered stage dicts plus a trigger. */
export interface PipelineRecord {
  id: string;
  name: string;
  description: string | null;
  trigger_type: string | null;
  is_active: boolean;
  stages: Array<{
    id?: string;
    name?: string;
    agent_id?: string | null;
    assignedAgent?: string;
    [field: string]: unknown;
  }>;
}

const company = (path: string) => `/api/v1/companies/${getActiveCompanyId()}${path}`;

export const listDepartments = () => apiClient.get<Department[]>(company('/departments'));
export const listTeams = () => apiClient.get<Team[]>(company('/teams'));
export const listDelegations = () => apiClient.get<Delegation[]>(company('/delegations'));
export const listPipelines = () => apiClient.get<PipelineRecord[]>(company('/pipelines'));
export const listToolConnections = () => apiClient.get<ToolConnection[]>('/api/v1/tool-connections');

export const listConnectionTools = (connectionId: string) =>
  apiClient.get<CatalogTool[]>(`/api/v1/tool-connections/${connectionId}/tools`);

export const listAgentBindings = (agentId: string) =>
  apiClient.get<McpBinding[]>(`/api/v1/agents/${agentId}/mcp-bindings`);

export const getAgentEffectiveTools = (agentId: string) =>
  apiClient.get<EffectiveTool[]>(`/api/v1/agents/${agentId}/effective-tools`);

export function createBinding(
  target: { agentId: string } | { sessionId: string },
  connectionId: string
): Promise<McpBinding> {
  const path =
    'sessionId' in target
      ? `/api/v1/sessions/${target.sessionId}/mcp-bindings`
      : `/api/v1/agents/${target.agentId}/mcp-bindings`;
  return apiClient.post<McpBinding>(path, { connection_id: connectionId });
}

export const setBindingStatus = (bindingId: string, status: 'active' | 'disabled') =>
  apiClient.patch<McpBinding>(`/api/v1/mcp-bindings/${bindingId}`, { status });

export const deleteBinding = (bindingId: string) =>
  apiClient.delete<void>(`/api/v1/mcp-bindings/${bindingId}`);

/** Set who an agent reports to; `null` clears the line. */
export const setManager = (agentId: string, managerId: string | null) =>
  apiClient.put<unknown>(`/api/v1/agents/${agentId}/manager`, { manager_id: managerId });

export const canvasKeys = {
  /** Shared with the workspace rail, so a reporting-line change refreshes both. */
  agents: () => ['agents', getActiveCompanyId()] as const,
  departments: () => ['canvas', 'departments', getActiveCompanyId()] as const,
  teams: () => ['canvas', 'teams', getActiveCompanyId()] as const,
  delegations: () => ['canvas', 'delegations', getActiveCompanyId()] as const,
  pipelines: () => ['canvas', 'pipelines', getActiveCompanyId()] as const,
  connections: () => ['canvas', 'connections', getActiveCompanyId()] as const,
  connectionTools: (id: string) => ['canvas', 'connection-tools', id] as const,
  agentBindings: (id: string) => ['canvas', 'agent-bindings', id] as const,
  agentTools: (id: string) => ['canvas', 'agent-tools', id] as const,
};

/**
 * Everything a topology change can make stale: canvas reads, the agent list,
 * and the workspace context panel's session bindings and tools.
 */
export function isTopologyQuery(queryKey: readonly unknown[]): boolean {
  return (
    queryKey[0] === 'canvas' ||
    queryKey[0] === 'agents' ||
    (queryKey[0] === 'sessions' && (queryKey[1] === 'bindings' || queryKey[1] === 'tools'))
  );
}
