import { apiClient } from './client';
import type { Agent, AgentCreateRequest, AgentUpdateRequest, MemoryEntry } from '@/types/agent';
import type { UUID } from '@/types/common';

const basePath = (companyId: UUID) => `/api/v1/companies/${companyId}/agents`;

export const agentsApi = {
  /** List all agents for a company. Backend returns Agent[] directly. */
  list(companyId: UUID, params?: { page_size?: number }): Promise<Agent[]> {
    return apiClient.get<Agent[]>(basePath(companyId), params);
  },

  /** Get single agent by ID (uses /api/v1/agents/{id} with X-Company-Id header) */
  get(agentId: UUID): Promise<Agent> {
    return apiClient.get<Agent>(`/api/v1/agents/${agentId}`);
  },

  /** Create a new agent */
  create(companyId: UUID, data: AgentCreateRequest): Promise<Agent> {
    return apiClient.post<Agent>(basePath(companyId), data);
  },

  /** Update an agent */
  update(agentId: UUID, data: AgentUpdateRequest): Promise<Agent> {
    return apiClient.put<Agent>(`/api/v1/agents/${agentId}`, data);
  },

  /** Delete an agent */
  delete(agentId: UUID): Promise<void> {
    return apiClient.delete<void>(`/api/v1/agents/${agentId}`);
  },

  /** Wake an agent */
  wake(agentId: UUID): Promise<Agent> {
    return apiClient.post<Agent>(`/api/v1/agents/${agentId}/wake`);
  },

  /** Pause an agent */
  pause(agentId: UUID): Promise<Agent> {
    return apiClient.post<Agent>(`/api/v1/agents/${agentId}/pause`);
  },

  /** Get agent memory */
  getMemory(agentId: UUID, params?: { limit?: number }): Promise<MemoryEntry[]> {
    return apiClient.get<MemoryEntry[]>(`/api/v1/agents/${agentId}/memory`, params);
  },
};
