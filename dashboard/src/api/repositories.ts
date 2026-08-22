import { apiClient } from './client';
import { COMPANY_ID } from '@/config';
import type {
  Repository,
  RepoCreateRequest,
  RepoUpdateRequest,
  RepoSyncResponse,
} from '@/types/repository';

export const repositoriesApi = {
  /** List connected repositories for company */
  list: (companyId: string = COMPANY_ID, limit: number = 50): Promise<Repository[]> =>
    apiClient.get<Repository[]>(`/api/v1/companies/${companyId}/repos`, { limit }),

  /** Connect a new repository */
  connect: (body: RepoCreateRequest, companyId: string = COMPANY_ID): Promise<Repository> =>
    apiClient.post<Repository>(`/api/v1/companies/${companyId}/repos`, body),

  /** Get repository details */
  get: (repoId: string): Promise<Repository> =>
    apiClient.get<Repository>(`/api/v1/repos/${repoId}`),

  /** Update repository configuration */
  update: (repoId: string, body: RepoUpdateRequest): Promise<Repository> =>
    apiClient.put<Repository>(`/api/v1/repos/${repoId}`, body),

  /** Disconnect / delete repository */
  disconnect: (repoId: string): Promise<void> =>
    apiClient.delete<void>(`/api/v1/repos/${repoId}`),

  /** Trigger repository commit/PR sync */
  sync: (repoId: string): Promise<RepoSyncResponse> =>
    apiClient.post<RepoSyncResponse>(`/api/v1/repos/${repoId}/sync`),
};
