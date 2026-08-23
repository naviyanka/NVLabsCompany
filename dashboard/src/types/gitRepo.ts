export type GitProvider = 'github' | 'gitlab' | 'bitbucket' | 'internal';

export interface GitCommit {
  hash: string;
  message: string;
  author: string;
  author_avatar?: string;
  relative_time: string;
  timestamp: string;
  additions: number;
  deletions: number;
  ast_indexed: boolean;
}

export interface PRReviewer {
  agent_name: string;
  decision: 'approved' | 'changes_requested' | 'commented' | 'pending';
  comment: string;
  timestamp: string;
}

export interface GitPullRequest {
  id: string;
  number: number;
  title: string;
  description: string;
  author: string;
  author_role?: string;
  status: 'open' | 'merged' | 'closed' | 'draft';
  checks: 'passed' | 'running' | 'failed' | 'pending';
  source_branch: string;
  target_branch: string;
  additions: number;
  deletions: number;
  changed_files_count: number;
  created_at: string;
  updated_at: string;
  ai_review_score: number;
  ai_summary: string;
  reviewers: PRReviewer[];
  diff_preview?: string;
}

export interface GitBranch {
  name: string;
  is_protected: boolean;
  last_commit_hash: string;
  last_commit_message: string;
  last_commit_time: string;
}

export interface GitContributor {
  name: string;
  role: string;
  commits: number;
}

export interface GitRepoItem {
  id: string;
  name: string;
  description?: string;
  provider: GitProvider;
  visibility?: 'private' | 'public' | 'internal';
  default_branch: string;
  language: string;
  stars_or_watchers?: number;
  sync_status: 'synced' | 'syncing' | 'error' | 'pending';
  last_sync_at: string;
  ast_index_coverage: number;
  security_score: number;
  open_prs_count: number;
  total_commits_7d: number;
  lines_of_code?: number;
  assigned_agents: string[];
  auto_review_enabled?: boolean;
  webhook_url?: string;
  branches: GitBranch[];
  commits: GitCommit[];
  prs: GitPullRequest[];
  contributors: GitContributor[];
}

export interface AggregatedPR extends GitPullRequest {
  repo_id: string;
  repo_name: string;
  repo_language: string;
  repo_default_branch?: string;
}

export interface AggregatedCommit extends GitCommit {
  repo_id: string;
  repo_name: string;
  repo_language: string;
  repo_default_branch?: string;
}
