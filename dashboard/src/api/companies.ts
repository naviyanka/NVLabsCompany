import { apiClient } from './client';
import type { Company, CompanyCreateRequest } from '@/types/company';
import type { PaginatedResponse, ListParams, UUID } from '@/types/common';

const basePath = '/api/v1/companies';

export const companiesApi = {
  list(params?: ListParams): Promise<PaginatedResponse<Company>> {
    return apiClient.get<PaginatedResponse<Company>>(basePath, params);
  },

  get(companyId: UUID): Promise<Company> {
    return apiClient.get<Company>(`${basePath}/${companyId}`);
  },

  create(data: CompanyCreateRequest): Promise<Company> {
    return apiClient.post<Company>(basePath, data);
  },

  update(companyId: UUID, data: Partial<CompanyCreateRequest>): Promise<Company> {
    return apiClient.patch<Company>(`${basePath}/${companyId}`, data);
  },

  delete(companyId: UUID): Promise<void> {
    return apiClient.delete<void>(`${basePath}/${companyId}`);
  },
};
