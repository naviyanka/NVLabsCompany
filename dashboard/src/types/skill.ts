export type SkillSourceType = 'zip' | 'command' | 'github' | 'custom';
export type SkillCategory = 'Engineering' | 'Security' | 'QA' | 'AI & Research' | 'Frontend' | 'DevOps' | 'Data & Analytics';

export interface SkillItem {
  id: string;
  name: string;
  category: SkillCategory;
  description: string;
  source_type: SkillSourceType;
  source_location?: string;
  version: string;
  author: string;
  enabled: boolean;
  security_status: 'verified' | 'sandboxed' | 'unverified';
  call_count_30d: number;
  success_rate: string;
  avg_execution_ms: number;
  equipped_agents: string[];
  instructions_md?: string;
  parameters_json?: string;
  created_at: string;
  updated_at: string;
}

export interface SkillTestResult {
  success: boolean;
  output: string;
  execution_ms: number;
  tokens_used?: number;
  error?: string;
}
