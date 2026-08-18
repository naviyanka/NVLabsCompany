import { apiClient } from './client';
import type { BudgetPolicy, BudgetUsage, Approval, ApprovalDecisionRequest } from '@/types/company';
import type { PaginatedResponse, ListParams, UUID } from '@/types/common';

const budgetPath = (companyId: UUID) => `/api/v1/companies/${companyId}/budget-policies`;
const usagePath = (companyId: UUID) => `/api/v1/companies/${companyId}/budget-usage`;
const approvalsPath = (companyId: UUID) => `/api/v1/companies/${companyId}/approvals`;

export const budgetsApi = {
  listPolicies(companyId: UUID, params?: ListParams): Promise<PaginatedResponse<BudgetPolicy>> {
    return apiClient.get<PaginatedResponse<BudgetPolicy>>(budgetPath(companyId), params);
  },

  getUsage(companyId: UUID): Promise<BudgetUsage[]> {
    return apiClient.get<BudgetUsage[]>(usagePath(companyId));
  },

  listApprovals(companyId: UUID, params?: ListParams): Promise<PaginatedResponse<Approval>> {
    return apiClient.get<PaginatedResponse<Approval>>(approvalsPath(companyId), params);
  },

  listPendingApprovals(companyId: UUID): Promise<Approval[]> {
    return apiClient.get<Approval[]>(`${approvalsPath(companyId)}/pending`);
  },

  decideApproval(companyId: UUID, approvalId: UUID, decision: ApprovalDecisionRequest): Promise<Approval> {
    return apiClient.post<Approval>(`${approvalsPath(companyId)}/${approvalId}/decide`, decision);
  },
};
