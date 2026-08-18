import { apiClient } from './client';
import type { WorkflowStatusResponse, WorkflowStep } from '@/types/evolution';
import type { UUID } from '@/types/common';

export interface StartWorkflowRequest {
  company_id: UUID;
  objective: string;
}

export const workflowsApi = {
  start(data: StartWorkflowRequest): Promise<WorkflowStatusResponse> {
    return apiClient.post<WorkflowStatusResponse>('/api/v1/workflows/company-flow', data);
  },

  getStatus(workflowId: string): Promise<WorkflowStatusResponse> {
    return apiClient.get<WorkflowStatusResponse>(`/api/v1/workflows/${workflowId}/status`);
  },

  getSteps(workflowId: string): Promise<WorkflowStep[]> {
    return apiClient.get<WorkflowStep[]>(`/api/v1/workflows/${workflowId}/steps`);
  },
};
