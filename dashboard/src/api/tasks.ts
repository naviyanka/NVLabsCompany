import { apiClient } from './client';
import type { Task, TaskCreateRequest, TaskUpdateRequest } from '@/types/task';
import type { PaginatedResponse, ListParams, UUID } from '@/types/common';

const basePath = (companyId: UUID) => `/api/v1/companies/${companyId}/tasks`;

export const tasksApi = {
  list(companyId: UUID, params?: ListParams): Promise<PaginatedResponse<Task>> {
    return apiClient.get<PaginatedResponse<Task>>(basePath(companyId), params);
  },

  get(companyId: UUID, taskId: UUID): Promise<Task> {
    return apiClient.get<Task>(`${basePath(companyId)}/${taskId}`);
  },

  create(companyId: UUID, data: TaskCreateRequest): Promise<Task> {
    return apiClient.post<Task>(basePath(companyId), data);
  },

  update(companyId: UUID, taskId: UUID, data: TaskUpdateRequest): Promise<Task> {
    return apiClient.patch<Task>(`${basePath(companyId)}/${taskId}`, data);
  },

  delete(companyId: UUID, taskId: UUID): Promise<void> {
    return apiClient.delete<void>(`${basePath(companyId)}/${taskId}`);
  },
};
