import { apiClient } from './client';
import type { Proposal, Evaluation } from '@/types/evolution';
import type { PaginatedResponse, ListParams, UUID } from '@/types/common';

const basePath = (companyId: UUID) => `/api/v1/companies/${companyId}/evolution`;

export const evolutionApi = {
  listProposals(companyId: UUID, params?: ListParams): Promise<PaginatedResponse<Proposal>> {
    return apiClient.get<PaginatedResponse<Proposal>>(`${basePath(companyId)}/proposals`, params);
  },

  getProposal(companyId: UUID, proposalId: UUID): Promise<Proposal> {
    return apiClient.get<Proposal>(`${basePath(companyId)}/proposals/${proposalId}`);
  },

  listEvaluations(companyId: UUID, params?: ListParams): Promise<PaginatedResponse<Evaluation>> {
    return apiClient.get<PaginatedResponse<Evaluation>>(`${basePath(companyId)}/evaluations`, params);
  },

  getEvaluation(companyId: UUID, evaluationId: UUID): Promise<Evaluation> {
    return apiClient.get<Evaluation>(`${basePath(companyId)}/evaluations/${evaluationId}`);
  },
};
