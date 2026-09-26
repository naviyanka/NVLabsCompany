/**
 * Sessions API module — the agent sessions the workspace works in.
 *
 * Everything here is server state. The backend owns session status, pins,
 * bindings and tool access; the UI reads it through React Query and never
 * keeps its own copy.
 */

import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';

export type SessionStatus = 'active' | 'idle' | 'completed' | 'terminated' | string;

export interface Session {
  id: string;
  company_id: string;
  agent_id: string;
  workspace_id: string | null;
  status: SessionStatus;
  title: string | null;
  adapter_type: string | null;
  model: string | null;
  llm_connection_id: string | null;
  external_session_id: string | null;
  event_seq: number;
  created_by: string | null;
  metadata: Record<string, unknown> | null;
  started_at: string;
  last_activity_at: string;
  ended_at: string | null;
}

export interface TimelineItem {
  type: 'message' | 'tool_call' | 'usage' | 'checkpoint';
  id: string;
  at: string;
  [field: string]: unknown;
}

export interface SessionUsage {
  session_id: string;
  events: number;
  cost_cents: number;
  input_tokens: number;
  output_tokens: number;
}

export interface McpBinding {
  id: string;
  connection_id: string;
  target_type: string;
  agent_id: string | null;
  session_id: string | null;
  disabled_tools: string[];
  instructions: string | null;
  status: string;
  version: number;
}

export interface EffectiveTool {
  connection_id: string;
  tool_name: string;
  risk_level: string;
  outcome: string;
  problems: Array<Record<string, unknown>>;
}

/** Sessions of the active company, newest activity first. */
export async function listSessions(agentId?: string): Promise<Session[]> {
  const page = await apiClient.get<{ items: Session[] }>(
    `/api/v1/companies/${getActiveCompanyId()}/sessions`,
    { agent_id: agentId }
  );
  return page.items;
}

export function getSession(sessionId: string): Promise<Session> {
  return apiClient.get<Session>(`/api/v1/sessions/${sessionId}`);
}

export function createSession(agentId: string, title?: string): Promise<Session> {
  return apiClient.post<Session>(`/api/v1/agents/${agentId}/sessions`, { title: title || null });
}

export function terminateSession(sessionId: string): Promise<Session> {
  return apiClient.post<Session>(`/api/v1/sessions/${sessionId}/terminate`);
}

/** First page of the merged timeline (messages, tool calls, usage, checkpoints). */
export async function getTimeline(sessionId: string): Promise<TimelineItem[]> {
  const page = await apiClient.get<{ items: TimelineItem[] }>(
    `/api/v1/sessions/${sessionId}/timeline?limit=500`
  );
  return page.items;
}

export function getUsage(sessionId: string): Promise<SessionUsage> {
  return apiClient.get<SessionUsage>(`/api/v1/sessions/${sessionId}/usage`);
}

export function sendMessage(sessionId: string, prompt: string): Promise<unknown> {
  return apiClient.post(`/api/v1/sessions/${sessionId}/messages`, { prompt });
}

export function listSessionBindings(sessionId: string): Promise<McpBinding[]> {
  return apiClient.get<McpBinding[]>(`/api/v1/sessions/${sessionId}/mcp-bindings`);
}

/** The server's access decision for every tool in the session's scope. */
export function getSessionEffectiveTools(sessionId: string): Promise<EffectiveTool[]> {
  return apiClient.get<EffectiveTool[]>(`/api/v1/sessions/${sessionId}/effective-tools`);
}

/** Query keys, so the page and its realtime handler invalidate the same entries. */
export const sessionKeys = {
  all: ['sessions'] as const,
  list: (agentId?: string) => ['sessions', 'list', getActiveCompanyId(), agentId ?? null] as const,
  detail: (id: string) => ['sessions', 'detail', id] as const,
  timeline: (id: string) => ['sessions', 'timeline', id] as const,
  usage: (id: string) => ['sessions', 'usage', id] as const,
  bindings: (id: string) => ['sessions', 'bindings', id] as const,
  tools: (id: string) => ['sessions', 'tools', id] as const,
};
