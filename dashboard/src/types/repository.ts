export interface Repository {
  id: string;
  company_id: string;
  name: string;
  url: string;
  provider: string;
  default_branch: string;
  description: string | null;
  language: string | null;
  is_active: boolean;
  last_synced_at: string | null;
  stats: Record<string, any> | null;
  created_at: string;
  updated_at: string;
}

export interface RepoCreateRequest {
  name: string;
  url: string;
  provider?: string;
  default_branch?: string;
  description?: string;
  language?: string;
}

export interface RepoUpdateRequest {
  name?: string;
  description?: string;
  default_branch?: string;
  is_active?: boolean;
}

export interface RepoSyncResponse {
  repo_id: string;
  synced_at: string;
}
