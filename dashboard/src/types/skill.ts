export type SkillSourceType = 'zip' | 'command' | 'github' | 'custom';
export type SkillCategory = 'Engineering' | 'Security' | 'QA' | 'AI & Research' | 'Frontend' | 'DevOps' | 'Data & Analytics';

/**
 * Mirrors SkillResponse from src/nexus/api/routes/skills.py.
 * Required fields are the only ones the backend guarantees; everything below
 * schema_def is client-side/aspirational and is never sent by the API today.
 */
export interface SkillItem {
  id: string;
  company_id: string;
  name: string;
  version: string;
  created_at: string;
  description?: string | null;
  category?: string | null;
  schema_def?: Record<string, unknown> | null;

  // Not returned by the backend — optional, do not assume present.
  source_type?: string | null;
  source_location?: string | null;
  author?: string | null;
  enabled?: boolean | null;
  security_status?: 'verified' | 'sandboxed' | 'unverified' | null;
  call_count_30d?: number | null;
  success_rate?: string | null;
  avg_execution_ms?: number | null;
  equipped_agents?: string[] | null;
  instructions_md?: string | null;
  parameters_json?: string | null;
  updated_at?: string | null;
}

export interface SkillTestResult {
  success: boolean;
  output: string;
  execution_ms?: number;
  tokens_used?: number;
  error?: string;
}
