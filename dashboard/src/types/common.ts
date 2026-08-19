/** UUID represented as a string */
export type UUID = string;

/** ISO 8601 datetime string */
export type DateTimeString = string;

/** Paginated list response wrapper */
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** Generic API error */
export interface ApiError {
  detail: string;
  status_code: number;
}

/** Query parameters for list endpoints */
export interface ListParams {
  [key: string]: string | number | undefined;
  page?: number;
  page_size?: number;
  sort_by?: string;
  sort_order?: 'asc' | 'desc';
}

/** Status types used across entities */
export type AgentStatus = 'active' | 'idle' | 'busy' | 'offline' | 'error';
export type TaskStatus = 'pending' | 'assigned' | 'in_progress' | 'completed' | 'failed' | 'cancelled';
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired';
export type ProposalStatus = 'draft' | 'proposed' | 'evaluating' | 'approved' | 'rejected' | 'deployed';
export type CompanyStatus = 'active' | 'inactive' | 'suspended';
export type WorkflowStatus = 'running' | 'completed' | 'failed' | 'cancelled';

/** Budget scope types */
export type BudgetScopeType = 'company' | 'department' | 'team' | 'agent';

/** Budget metric types */
export type BudgetMetric = 'cost' | 'tokens' | 'requests';

/** Budget window types */
export type BudgetWindowKind = 'daily' | 'weekly' | 'monthly';

/** Memory tier types */
export type MemoryTier = 'hot' | 'warm' | 'cold';

/** Memory scope types */
export type MemoryScope = 'agent' | 'team' | 'department' | 'company';
