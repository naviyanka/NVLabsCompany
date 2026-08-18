import { apiClient } from './client';
import type { Agent, AgentCreateRequest, AgentUpdateRequest, MemoryEntry } from '@/types/agent';
import type { PaginatedResponse, ListParams, UUID } from '@/types/common';

const basePath = (companyId: UUID) => `/api/v1/companies/${companyId}/agents`;

export const agentsApi = {
  list(companyId: UUID, params?: ListParams): Promise<PaginatedResponse<Agent>> {
    return apiClient.get<PaginatedResponse<Agent>>(basePath(companyId), params);
  },

  get(companyId: UUID, agentId: UUID): Promise<Agent> {
    return apiClient.get<Agent>(`${basePath(companyId)}/${agentId}`);
  },

  create(companyId: UUID, data: AgentCreateRequest): Promise<Agent> {
    return apiClient.post<Agent>(basePath(companyId), data);
  },

  update(companyId: UUID, agentId: UUID, data: AgentUpdateRequest): Promise<Agent> {
    return apiClient.patch<Agent>(`${basePath(companyId)}/${agentId}`, data);
  },

  delete(companyId: UUID, agentId: UUID): Promise<void> {
    return apiClient.delete<void>(`${basePath(companyId)}/${agentId}`);
  },

  getMemory(agentId: UUID, params?: ListParams): Promise<PaginatedResponse<MemoryEntry>> {
    return apiClient.get<PaginatedResponse<MemoryEntry>>(`/api/v1/agents/${agentId}/memory`, params);
  },

  searchMemory(companyId: UUID, query: string): Promise<MemoryEntry[]> {
    return apiClient.post<MemoryEntry[]>(`/api/v1/companies/${companyId}/memory/search`, { query });
  },
};
