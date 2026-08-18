import { agentsApi } from '@/api/agents';
import { useApi } from './useApi';
import type { Agent } from '@/types/agent';
import type { PaginatedResponse, ListParams, UUID } from '@/types/common';

export function useAgents(companyId: UUID, params?: ListParams) {
  return useApi<PaginatedResponse<Agent>>(
    () => agentsApi.list(companyId, params),
    [companyId, params?.page, params?.page_size]
  );
}

export function useAgent(companyId: UUID, agentId: UUID) {
  return useApi<Agent>(
    () => agentsApi.get(companyId, agentId),
    [companyId, agentId]
  );
}
