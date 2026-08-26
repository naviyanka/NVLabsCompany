/**
 * Enhanced Hire Agent Modal — 3 modes: Manual, From Template, Hire a Team.
 */

import {
  createAgent,
  listArchetypes,
  listProviderModels,
  listProviders,
  listSoulTemplates,
  type AgentArchetype,
  type AgentProvider,
  type ProviderModel,
  type SoulTemplate,
} from '@/api/agents';
import { ArchetypeGrid } from '@/components/agents/ArchetypeGrid';
import { ManifestImport } from '@/components/agents/ManifestImport';
import { TeamHireFlow } from '@/components/agents/TeamHireFlow';
import { Button } from '@/components/common/Button';
import { Modal } from '@/components/common/Modal';
import { ArrowLeft, Circle, FileJson, LayoutTemplate, UserPlus, Users } from 'lucide-react';
import { useEffect, useState } from 'react';

type HireMode = 'select' | 'manual' | 'template' | 'team' | 'manifest';

// Fallback archetypes when the backend API is unavailable (e.g. mock server mode)
const FALLBACK_ARCHETYPES: AgentArchetype[] = [
  { name: 'Software Architect', role: 'software-architect', capabilities: ['system-design', 'trade-off-analysis', 'domain-modeling', 'technology-selection', 'scalability-planning'], constraints: ['must document all architectural decisions', 'no premature optimization', 'prefer composition over inheritance'], system_prompt: 'You are a senior software architect responsible for designing robust, scalable systems.', tools_allowed: ['code-analysis', 'diagram-generation', 'documentation', 'search'], interaction_style: 'analytical', description: 'Designs system architecture, evaluates trade-offs, and documents decisions.' },
  { name: 'Backend Engineer', role: 'backend-engineer', capabilities: ['api-design', 'database-modeling', 'server-side-logic', 'performance-tuning', 'integration-development'], constraints: ['must write unit tests for all new code', 'follow RESTful conventions', 'no hardcoded secrets in source'], system_prompt: 'You are a backend engineer who builds reliable server-side applications.', tools_allowed: ['code-editor', 'terminal', 'database-client', 'api-testing'], interaction_style: 'methodical', description: 'Builds server-side applications, APIs, and integrations with databases.' },
  { name: 'Frontend Engineer', role: 'frontend-engineer', capabilities: ['ui-development', 'component-design', 'state-management', 'responsive-design', 'accessibility-implementation'], constraints: ['must ensure WCAG 2.1 AA compliance', 'no inline styles in production code', 'components must be reusable and composable'], system_prompt: 'You are a frontend engineer focused on building intuitive, performant user interfaces.', tools_allowed: ['code-editor', 'browser-devtools', 'design-tools', 'terminal'], interaction_style: 'creative', description: 'Creates user interfaces with reusable components and responsive design.' },
  { name: 'QA Engineer', role: 'qa-engineer', capabilities: ['test-planning', 'automated-testing', 'regression-analysis', 'bug-reporting', 'test-coverage-analysis'], constraints: ['must document all test scenarios before execution', 'no test without assertion', 'report severity and reproduction steps for every bug'], system_prompt: 'You are a QA engineer dedicated to ensuring software quality through comprehensive testing strategies.', tools_allowed: ['test-runner', 'code-editor', 'bug-tracker', 'browser-devtools'], interaction_style: 'methodical', description: 'Ensures software quality through test planning, automation, and defect tracking.' },
  { name: 'DevOps Engineer', role: 'devops-engineer', capabilities: ['ci-cd-pipeline-design', 'infrastructure-as-code', 'container-orchestration', 'monitoring-setup', 'deployment-automation'], constraints: ['must use infrastructure as code for all changes', 'no manual configuration in production', 'all deployments must be rollback-capable'], system_prompt: 'You are a DevOps engineer who bridges development and operations.', tools_allowed: ['terminal', 'cloud-console', 'monitoring-dashboard', 'code-editor'], interaction_style: 'directive', description: 'Manages CI/CD pipelines, infrastructure as code, and deployment automation.' },
  { name: 'Security Engineer', role: 'security-engineer', capabilities: ['threat-modeling', 'vulnerability-assessment', 'security-code-review', 'penetration-testing', 'compliance-auditing'], constraints: ['must follow responsible disclosure practices', 'no security through obscurity', 'document all identified vulnerabilities with CVSS scores'], system_prompt: 'You are a security engineer focused on protecting systems from threats.', tools_allowed: ['code-analysis', 'security-scanner', 'terminal', 'documentation'], interaction_style: 'analytical', description: 'Protects systems through threat modeling, security reviews, and vulnerability assessment.' },
  { name: 'Data Engineer', role: 'data-engineer', capabilities: ['data-pipeline-design', 'etl-development', 'data-modeling', 'query-optimization', 'data-quality-assurance'], constraints: ['must validate data at ingestion boundaries', 'no data transformations without audit trail', 'ensure idempotent pipeline operations'], system_prompt: 'You are a data engineer who builds and maintains data infrastructure.', tools_allowed: ['database-client', 'code-editor', 'terminal', 'data-catalog'], interaction_style: 'methodical', description: 'Builds data pipelines, models warehouses, and ensures data quality.' },
  { name: 'ML Engineer', role: 'ml-engineer', capabilities: ['model-training', 'feature-engineering', 'model-deployment', 'experiment-tracking', 'hyperparameter-optimization'], constraints: ['must version all models and datasets', 'no model deployment without evaluation metrics', 'document all experiment parameters and results'], system_prompt: 'You are a machine learning engineer who brings ML models from research to production.', tools_allowed: ['code-editor', 'terminal', 'notebook', 'experiment-tracker', 'cloud-console'], interaction_style: 'analytical', description: 'Trains, evaluates, and deploys machine learning models to production.' },
  { name: 'Product Manager', role: 'product-manager', capabilities: ['requirements-gathering', 'roadmap-planning', 'stakeholder-communication', 'prioritization', 'user-story-writing'], constraints: ['must validate assumptions with data or user research', 'no feature without clear success metrics', 'prioritize based on impact and effort'], system_prompt: 'You are a product manager who translates business goals into actionable development plans.', tools_allowed: ['documentation', 'project-tracker', 'analytics-dashboard'], interaction_style: 'collaborative', description: 'Translates business goals into development plans and manages the product roadmap.' },
  { name: 'Technical Writer', role: 'tech-writer', capabilities: ['documentation-writing', 'api-documentation', 'tutorial-creation', 'style-guide-enforcement'], constraints: ['must follow established style guide', 'no jargon without definition', 'include code examples for all API endpoints'], system_prompt: 'You are a technical writer who creates clear, accurate documentation for software products.', tools_allowed: ['documentation', 'code-editor', 'search'], interaction_style: 'supportive', description: 'Creates clear technical documentation, API references, and developer guides.' },
  { name: 'Designer', role: 'designer', capabilities: ['ui-design', 'ux-research', 'prototyping', 'design-system-management', 'user-flow-mapping'], constraints: ['must validate designs with user feedback', 'follow established design system tokens', 'ensure designs are implementable within technical constraints'], system_prompt: 'You are a product designer who creates intuitive, beautiful interfaces.', tools_allowed: ['design-tools', 'prototyping-tool', 'documentation', 'browser-devtools'], interaction_style: 'creative', description: 'Designs user interfaces and experiences through research, prototyping, and visual design.' },
  { name: 'Researcher', role: 'researcher', capabilities: ['literature-review', 'experiment-design', 'data-analysis', 'hypothesis-formulation', 'technical-writing'], constraints: ['must cite sources for all claims', 'no conclusions without supporting evidence', 'document methodology for reproducibility'], system_prompt: 'You are a technical researcher who explores emerging technologies and methodologies.', tools_allowed: ['search', 'documentation', 'code-editor', 'data-analysis'], interaction_style: 'analytical', description: 'Explores technologies through literature review, experimentation, and data analysis.' },
  { name: 'Project Manager', role: 'project-manager', capabilities: ['project-planning', 'resource-allocation', 'risk-management', 'status-reporting', 'timeline-estimation'], constraints: ['must track all risks with mitigation plans', 'no scope changes without impact assessment', 'weekly status updates required'], system_prompt: 'You are a project manager who ensures projects are delivered on time and within scope.', tools_allowed: ['project-tracker', 'documentation', 'analytics-dashboard'], interaction_style: 'directive', description: 'Plans projects, allocates resources, and tracks delivery against timelines.' },
  { name: 'Scrum Master', role: 'scrum-master', capabilities: ['ceremony-facilitation', 'impediment-removal', 'process-improvement', 'team-coaching', 'metrics-tracking'], constraints: ['must protect the team from external disruptions', 'no dictating solutions to the team', 'retrospective actions must be tracked to completion'], system_prompt: 'You are a scrum master who facilitates agile processes and removes impediments for the development team.', tools_allowed: ['project-tracker', 'documentation', 'analytics-dashboard'], interaction_style: 'supportive', description: 'Facilitates agile processes, removes impediments, and coaches teams on practices.' },
  { name: 'Site Reliability Engineer', role: 'site-reliability-engineer', capabilities: ['incident-response', 'slo-management', 'capacity-planning', 'reliability-engineering', 'toil-reduction'], constraints: ['must maintain error budgets for all services', 'no changes without rollback plan', 'all incidents require post-mortem documentation'], system_prompt: 'You are a site reliability engineer who ensures production systems are reliable and performant.', tools_allowed: ['monitoring-dashboard', 'terminal', 'cloud-console', 'documentation'], interaction_style: 'methodical', description: 'Ensures system reliability through SLO management, incident response, and automation.' },
  { name: 'Database Administrator', role: 'database-admin', capabilities: ['database-design', 'performance-tuning', 'backup-recovery', 'replication-management', 'access-control'], constraints: ['must test all schema changes in staging first', 'no destructive operations without backup verification', 'maintain access audit logs'], system_prompt: 'You are a database administrator who manages and optimizes database systems.', tools_allowed: ['database-client', 'terminal', 'monitoring-dashboard'], interaction_style: 'methodical', description: 'Manages database systems including schema design, performance tuning, and backup recovery.' },
  { name: 'Mobile Developer', role: 'mobile-developer', capabilities: ['mobile-app-development', 'cross-platform-development', 'mobile-ui-design', 'offline-first-architecture', 'app-store-deployment'], constraints: ['must support minimum two OS versions back', 'no network calls without offline fallback', 'follow platform-specific design guidelines'], system_prompt: 'You are a mobile developer who builds native and cross-platform mobile applications.', tools_allowed: ['code-editor', 'device-emulator', 'terminal', 'design-tools'], interaction_style: 'creative', description: 'Builds mobile applications with offline support and platform-native experiences.' },
  { name: 'Performance Engineer', role: 'performance-engineer', capabilities: ['load-testing', 'profiling', 'bottleneck-analysis', 'optimization', 'capacity-modeling'], constraints: ['must establish baselines before optimization', 'no optimization without measurement', 'document all performance improvements with before/after metrics'], system_prompt: 'You are a performance engineer who identifies and resolves performance bottlenecks in software systems.', tools_allowed: ['profiler', 'load-testing-tool', 'monitoring-dashboard', 'terminal'], interaction_style: 'analytical', description: 'Identifies and resolves performance bottlenecks through profiling and load testing.' },
  { name: 'Accessibility Specialist', role: 'accessibility-specialist', capabilities: ['accessibility-auditing', 'assistive-technology-testing', 'wcag-compliance', 'inclusive-design'], constraints: ['must test with screen readers and keyboard navigation', 'no images without alt text', 'all interactive elements must have ARIA labels'], system_prompt: 'You are an accessibility specialist who ensures digital products are usable by people of all abilities.', tools_allowed: ['accessibility-scanner', 'browser-devtools', 'screen-reader', 'documentation'], interaction_style: 'supportive', description: 'Ensures digital products meet accessibility standards and are usable by all.' },
  { name: 'Team Lead', role: 'team-lead', capabilities: ['technical-leadership', 'code-review', 'mentoring', 'sprint-planning', 'cross-team-coordination', 'decision-making'], constraints: ['must delegate rather than do all work personally', 'no technical decisions without team input', 'maintain one-on-one cadence with all direct reports'], system_prompt: 'You are a team lead who combines technical expertise with people leadership.', tools_allowed: ['code-editor', 'project-tracker', 'documentation', 'code-analysis'], interaction_style: 'collaborative', description: 'Combines technical expertise with people leadership to guide team delivery.' },
  { name: 'HR Manager', role: 'hr-manager', capabilities: ['talent-acquisition', 'agent-onboarding', 'team-composition', 'workforce-planning', 'performance-management', 'role-definition', 'organizational-design'], constraints: ['must define clear responsibilities before hiring', 'must ensure new hires complement existing capabilities', 'must consider budget implications', 'must document hiring rationale'], system_prompt: 'You are an HR manager responsible for building high-performing teams. You define roles, recruit agents, manage onboarding, and ensure teams are well-balanced and productive.', tools_allowed: ['project-tracker', 'documentation', 'analytics-dashboard', 'search'], interaction_style: 'collaborative', description: 'Builds and manages teams through talent acquisition, onboarding, workforce planning, and role definition.' },
  { name: 'Hermes CEO', role: 'ceo', capabilities: ['strategic-planning', 'task-decomposition', 'tool-calling', 'autonomous-reasoning', 'pipeline-orchestration', 'budget-governance', 'workforce-delegation', 'memory-graph-management'], constraints: ['must verify task completion before declaring success', 'must isolate code edits in git worktrees', 'must log all actions to audit trail', 'must balance workload across workforce agents', 'must respect budget limits'], system_prompt: 'You are Navi, the Chief Executive Officer and Principal System Orchestrator of NVLabsCompany. Powered by Nous Research Hermes. You have full operational authority over all agents, tasks, pipelines, and workflows. Execute tool calls to delegate, coordinate, and verify work across the organization.', tools_allowed: ['task-create', 'task-delegate', 'pipeline-run', 'agent-wake', 'agent-pause', 'memory-store', 'plaza-broadcast', 'budget-check', 'git-worktree', 'code-analysis'], interaction_style: 'directive', description: 'Hermes-powered CEO with full orchestration authority. Uses the hermes CLI directly as backend. Manages the entire platform on demand: decomposes goals, delegates to workforce, monitors budgets, and ensures quality through autonomous tool calling.' },
  { name: 'Hermes Agent', role: 'hermes-agent', capabilities: ['function-calling', 'tool-execution', 'autonomous-reasoning', 'unaligned-problem-solving', 'structured-json-output'], constraints: ['must execute all function calls via sandbox', 'must log all context discoveries to Plaza Knowledge Feed'], system_prompt: 'You are Hermes, an autonomous agent powered by Nous Research Hermes 3. You excel at tool calling, function execution, and complex problem solving.', tools_allowed: ['code-editor', 'terminal', 'sandbox-runner', 'plaza-broadcast', 'gitnexus-analysis'], interaction_style: 'direct', description: 'Nous Research Hermes 3 autonomous tool execution and function-calling specialist. Can fill any role with direct, precise execution.' },
];

// Fallback providers when the backend API is unavailable
const FALLBACK_PROVIDERS: AgentProvider[] = [
  { id: 'hermes', label: 'Hermes 3 \u00b7 Nous Research', default_command: 'ollama run hermes3', auto_mode_flag: '', supports_model: true, model_flag: '--model', hive_aware: true, can_receive_inbox: true, recommended_model: 'hermes3:8b', resume_flag: null, install_command: 'ollama pull hermes3', docs_url: 'https://nousresearch.com/hermes', installed: true, version: '3.0' },
  { id: 'hermes-cli', label: 'Hermes Agent CLI \u00b7 CEO Mode', default_command: 'hermes', auto_mode_flag: '--yolo', supports_model: true, model_flag: '--model', hive_aware: true, can_receive_inbox: true, recommended_model: 'stealth/ox-alpha', resume_flag: '--resume', install_command: 'See https://nousresearch.com/hermes', docs_url: 'https://nousresearch.com/hermes', installed: true, version: '0.20.5' },
  { id: 'claude', label: 'Claude Code', default_command: 'claude', auto_mode_flag: '--permission-mode bypassPermissions', supports_model: true, model_flag: '--model', hive_aware: true, can_receive_inbox: true, recommended_model: 'claude-opus-4-8[1m]', resume_flag: '--resume', install_command: 'npm install -g @anthropic-ai/claude-code', docs_url: 'https://docs.claude.com/en/docs/claude-code', installed: false, version: null },
  { id: 'codex', label: 'Codex \u00b7 GPT', default_command: 'codex', auto_mode_flag: '--dangerously-bypass-approvals-and-sandbox', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: 'gpt-5-codex', resume_flag: null, install_command: 'npm install -g @openai/codex', docs_url: 'https://github.com/openai/codex', installed: false, version: null },
  { id: 'grok', label: 'Grok \u00b7 xAI', default_command: 'grok', auto_mode_flag: '--permission-mode bypassPermissions', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: null, resume_flag: '--resume', install_command: null, docs_url: null, installed: false, version: null },
  { id: 'kimi', label: 'Kimi Code', default_command: 'kimi', auto_mode_flag: '--auto', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: false, recommended_model: null, resume_flag: null, install_command: null, docs_url: null, installed: false, version: null },
  { id: 'antigravity', label: 'Antigravity \u00b7 Gemini', default_command: 'agy', auto_mode_flag: '--dangerously-skip-permissions', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: 'Gemini 3.1 Pro (High)', resume_flag: '--conversation', install_command: null, docs_url: null, installed: false, version: null },
  { id: 'qwen', label: 'Qwen (local available)', default_command: 'qwen', auto_mode_flag: '--yolo', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: 'qwen3-coder-plus', resume_flag: null, install_command: null, docs_url: null, installed: false, version: null },
  { id: 'opencode', label: 'OpenCode', default_command: 'opencode', auto_mode_flag: '', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: null, resume_flag: null, install_command: 'npm install -g opencode-ai@latest', docs_url: 'https://opencode.ai/docs', installed: false, version: null },
  { id: 'crush', label: 'Crush \u00b7 Charm', default_command: 'crush', auto_mode_flag: '--yolo', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: 'openai/gpt-4o', resume_flag: '--session', install_command: 'npm install -g @charmland/crush', docs_url: 'https://github.com/charmbracelet/crush', installed: false, version: null },
  { id: 'pi', label: 'Pi', default_command: 'pi', auto_mode_flag: '--approve', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: 'anthropic/claude-sonnet-4-5', resume_flag: '--session', install_command: 'npm install -g --ignore-scripts @earendil-works/pi-coding-agent', docs_url: 'https://pi.dev/docs/latest', installed: false, version: null },
  { id: 'copilot', label: 'Copilot', default_command: 'copilot', auto_mode_flag: '-s --allow-all-tools --no-ask-user', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: false, recommended_model: 'claude-sonnet-4.5', resume_flag: '--resume', install_command: 'npm install -g @github/copilot', docs_url: 'https://docs.github.com/copilot/concepts/agents/about-copilot-cli', installed: false, version: null },
  { id: 'kiro-cli', label: 'Kiro CLI', default_command: 'kiro', auto_mode_flag: '', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: true, recommended_model: null, resume_flag: null, install_command: null, docs_url: 'https://kiro.dev', installed: false, version: null },
  { id: 'aider', label: 'Aider', default_command: 'aider', auto_mode_flag: '--yes', supports_model: true, model_flag: '--model', hive_aware: false, can_receive_inbox: false, recommended_model: 'claude-sonnet-4', resume_flag: null, install_command: 'pip install aider-chat', docs_url: 'https://aider.chat', installed: false, version: null },
];

// Fallback model lists per provider for when API is unavailable
const FALLBACK_MODELS: Record<string, ProviderModel[]> = {
  hermes: [
    { id: 'hermes3:8b', name: 'Hermes 3 8B (local)', tier: 'fast' },
    { id: 'hermes3:70b', name: 'Hermes 3 70B (local)', tier: 'flagship' },
    { id: 'nousresearch/hermes-3-llama-3.1-405b', name: 'Hermes 3 405B (OpenRouter)', tier: 'flagship' },
    { id: 'nousresearch/hermes-3-llama-3.1-8b', name: 'Hermes 3 8B (OpenRouter)', tier: 'balanced' },
  ],
  'hermes-cli': [
    { id: 'stealth/ox-alpha', name: 'Stealth OX Alpha (default)', tier: 'flagship' },
    { id: 'nousresearch/hermes-4-405b', name: 'Hermes 4 405B', tier: 'flagship' },
    { id: 'nousresearch/hermes-4-70b', name: 'Hermes 4 70B', tier: 'balanced' },
    { id: 'poolside/laguna-s-2.1:free', name: 'Laguna S 2.1 (free)', tier: 'free' },
    { id: 'anthropic/claude-sonnet-4', name: 'Claude Sonnet 4 (via Nous)', tier: 'flagship' },
    { id: 'deepseek/deepseek-chat', name: 'DeepSeek Chat', tier: 'balanced' },
  ],
  claude: [
    { id: 'claude-sonnet-4-20250514', name: 'Claude Sonnet 4', tier: 'flagship' },
    { id: 'claude-opus-4-20250514', name: 'Claude Opus 4', tier: 'flagship' },
    { id: 'claude-haiku-4-20250514', name: 'Claude Haiku 4', tier: 'fast' },
    { id: 'claude-sonnet-4-5-20250514', name: 'Claude Sonnet 4.5', tier: 'flagship' },
    { id: 'claude-3-7-sonnet-20250219', name: 'Claude 3.7 Sonnet', tier: 'balanced' },
    { id: 'claude-3-5-haiku-20241022', name: 'Claude 3.5 Haiku', tier: 'fast' },
  ],
  codex: [
    { id: 'gpt-4o', name: 'GPT-4o', tier: 'flagship' },
    { id: 'gpt-4o-mini', name: 'GPT-4o Mini', tier: 'fast' },
    { id: 'o3', name: 'o3', tier: 'reasoning' },
    { id: 'o3-mini', name: 'o3 Mini', tier: 'reasoning' },
    { id: 'o4-mini', name: 'o4 Mini', tier: 'reasoning' },
    { id: 'gpt-4.1', name: 'GPT-4.1', tier: 'flagship' },
    { id: 'gpt-4.1-mini', name: 'GPT-4.1 Mini', tier: 'fast' },
  ],
  grok: [
    { id: 'grok-3', name: 'Grok 3', tier: 'flagship' },
    { id: 'grok-3-mini', name: 'Grok 3 Mini', tier: 'fast' },
    { id: 'grok-3-fast', name: 'Grok 3 Fast', tier: 'fast' },
  ],
  kimi: [
    { id: 'kimi-latest', name: 'Kimi Latest', tier: 'flagship' },
    { id: 'moonshot-v1-128k', name: 'Moonshot v1 128K', tier: 'flagship' },
  ],
  antigravity: [
    { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', tier: 'flagship' },
    { id: 'gemini-2.5-flash', name: 'Gemini 2.5 Flash', tier: 'fast' },
    { id: 'gemini-2.0-flash', name: 'Gemini 2.0 Flash', tier: 'fast' },
  ],
  qwen: [
    { id: 'qwen3-coder-plus', name: 'Qwen3 Coder Plus', tier: 'flagship' },
    { id: 'qwen3-coder', name: 'Qwen3 Coder', tier: 'balanced' },
    { id: 'qwen3-235b', name: 'Qwen3 235B', tier: 'flagship' },
  ],
  opencode: [
    { id: 'anthropic/claude-sonnet-4', name: 'Claude Sonnet 4', tier: 'flagship' },
    { id: 'openai/gpt-4o', name: 'GPT-4o', tier: 'flagship' },
  ],
  crush: [
    { id: 'openai/gpt-4o', name: 'GPT-4o', tier: 'flagship' },
    { id: 'anthropic/claude-sonnet-4', name: 'Claude Sonnet 4', tier: 'flagship' },
  ],
  pi: [
    { id: 'anthropic/claude-sonnet-4-5', name: 'Claude Sonnet 4.5', tier: 'flagship' },
    { id: 'anthropic/claude-sonnet-4', name: 'Claude Sonnet 4', tier: 'flagship' },
  ],
  copilot: [
    { id: 'claude-sonnet-4', name: 'Claude Sonnet 4', tier: 'flagship' },
    { id: 'gpt-4o', name: 'GPT-4o', tier: 'flagship' },
    { id: 'o3-mini', name: 'o3 Mini', tier: 'reasoning' },
    { id: 'gemini-2.5-pro', name: 'Gemini 2.5 Pro', tier: 'flagship' },
  ],
  'kiro-cli': [
    { id: 'auto', name: 'Auto (optimal per task)', tier: 'auto' },
    { id: 'claude-opus-5', name: 'Claude Opus 5', tier: 'flagship' },
    { id: 'claude-sonnet-5', name: 'Claude Sonnet 5', tier: 'flagship' },
    { id: 'claude-opus-4.8', name: 'Claude Opus 4.8', tier: 'flagship' },
    { id: 'claude-sonnet-4.6', name: 'Claude Sonnet 4.6', tier: 'balanced' },
    { id: 'gpt-5.6-sol', name: 'GPT 5.6 Sol', tier: 'flagship' },
    { id: 'deepseek-3.2', name: 'DeepSeek 3.2', tier: 'fast' },
    { id: 'qwen3-coder-next', name: 'Qwen3 Coder Next', tier: 'fast' },
  ],
  aider: [
    { id: 'claude-sonnet-4', name: 'Claude Sonnet 4 (via Anthropic)', tier: 'flagship' },
    { id: 'gpt-4o', name: 'GPT-4o (via OpenAI)', tier: 'flagship' },
    { id: 'deepseek/deepseek-chat', name: 'DeepSeek Chat', tier: 'balanced' },
    { id: 'ollama/llama3.1', name: 'Llama 3.1 (local)', tier: 'local' },
    { id: 'gemini/gemini-2.5-pro', name: 'Gemini 2.5 Pro', tier: 'flagship' },
  ],
};

interface HireAgentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function HireAgentModal({ isOpen, onClose, onSuccess }: HireAgentModalProps) {
  const [mode, setMode] = useState<HireMode>('select');
  const [archetypes, setArchetypes] = useState<AgentArchetype[]>(FALLBACK_ARCHETYPES);
  const [providers, setProviders] = useState<AgentProvider[]>(FALLBACK_PROVIDERS);
  const [soulTemplates, setSoulTemplates] = useState<SoulTemplate[]>([]);
  const [loadingMeta, setLoadingMeta] = useState(false);

  // Manual hire state
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [role, setRole] = useState('');
  const [model, setModel] = useState('');
  const [provider, setProvider] = useState('claude');
  const [providerModels, setProviderModels] = useState<ProviderModel[]>([]);
  const [showProviderMenu, setShowProviderMenu] = useState(false);
  const [capabilities, setCapabilities] = useState('');
  const [responsibilities, setResponsibilities] = useState('');
  const [objectives, setObjectives] = useState('');
  const [soulDescription, setSoulDescription] = useState('');
  const [budgetCents, setBudgetCents] = useState(0);
  const [personalityTraits, setPersonalityTraits] = useState('');
  const [communicationStyle, setCommunicationStyle] = useState('');
  const [agentValues, setAgentValues] = useState('');
  const [agentConstraints, setAgentConstraints] = useState('');
  const [tone, setTone] = useState('professional');
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load archetypes and providers when modal opens
  useEffect(() => {
    if (!isOpen) return;
    setLoadingMeta(true);
    Promise.all([listArchetypes(), listProviders(), listSoulTemplates()])
      .then(([archs, provs, souls]) => {
        if (Array.isArray(archs) && archs.length > 0) {
          setArchetypes(archs);
        }
        if (Array.isArray(provs) && provs.length > 0) {
          setProviders(provs);
        }
        if (Array.isArray(souls) && souls.length > 0) {
          setSoulTemplates(souls);
        }
      })
      .catch(() => {
        // API unavailable — keep fallback data (already in state)
      })
      .finally(() => setLoadingMeta(false));
  }, [isOpen]);

  // Reset state when modal closes
  useEffect(() => {
    if (!isOpen) {
      setMode('select');
      setName('');
      setTitle('');
      setRole('');
      setModel('');
      setCapabilities('');
      setResponsibilities('');
      setObjectives('');
      setSoulDescription('');
      setBudgetCents(0);
      setError(null);
    }
  }, [isOpen]);

  // Load models when provider changes
  useEffect(() => {
    if (!provider) return;
    // Immediately show fallback models (curated list per provider)
    setProviderModels(FALLBACK_MODELS[provider] || []);
    // Then try API for potentially fresher data
    listProviderModels(provider)
      .then((models) => {
        if (Array.isArray(models) && models.length > 0) {
          setProviderModels(models);
        }
      })
      .catch(() => {
        // Keep fallback models already set above
      });
  }, [provider]);

  const handleManualCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setCreating(true);
    setError(null);
    try {
      // Build rich soul description from persona fields
      const soulParts: string[] = [];
      if (soulDescription) soulParts.push(soulDescription);
      if (personalityTraits) soulParts.push(`Personality: ${personalityTraits}`);
      if (communicationStyle) soulParts.push(`Communication: ${communicationStyle}`);
      if (agentValues) soulParts.push(`Values: ${agentValues}`);
      if (agentConstraints) soulParts.push(`Constraints:\n${agentConstraints}`);
      if (tone && tone !== 'professional') soulParts.push(`Tone: ${tone}`);
      const fullSoulDescription = soulParts.join('\n\n') || undefined;

      await createAgent({
        name,
        title: title || 'Operations Specialist',
        role: role || 'engineer',
        adapter_type: provider || 'langchain',
        model: model || '',
        capabilities: capabilities ? capabilities.split(',').map((c) => c.trim()).filter(Boolean) : undefined,
        responsibilities: responsibilities || undefined,
        objectives: objectives || undefined,
        soul_description: fullSoulDescription,
        budget_monthly_cents: budgetCents || undefined,
      });
      onSuccess();
    } catch (err: any) {
      setError(err?.message || 'Agent deployment failed');
    } finally {
      setCreating(false);
    }
  };

  const handleTemplateSelect = (archetype: AgentArchetype) => {
    // Pre-fill manual form with archetype data
    setRole(archetype.role);
    setCapabilities(archetype.capabilities.join(', '));
    setSoulDescription(archetype.system_prompt);
    setTitle(archetype.name);

    // Auto-select Hermes provider for Hermes archetypes
    if (archetype.role === 'ceo' && archetype.name.toLowerCase().includes('hermes')) {
      setProvider('hermes-cli');
      setModel('');
    } else if (archetype.name.toLowerCase().includes('hermes')) {
      setProvider('hermes');
      setModel('hermes3:8b');
    }

    setMode('manual');
  };

  const modalTitle =
    mode === 'select'
      ? 'Hire Autonomous Agent'
      : mode === 'manual'
        ? 'Manual Agent Configuration'
        : mode === 'template'
          ? 'Hire from Archetype Template'
          : mode === 'manifest'
            ? 'Import from Manifest'
            : 'Hire a Team';

  return (
    <Modal isOpen={isOpen} onClose={onClose} title={modalTitle} size={mode === 'team' || mode === 'template' ? 'lg' : 'md'}>
      {/* Mode Selection Screen */}
      {mode === 'select' && (
        <div className="space-y-4">
          <p className="text-xs text-[#9C9C9F] font-mono">
            Choose how you'd like to onboard new agents into the workforce.
          </p>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {/* Manual Hire */}
            <button
              onClick={() => setMode('manual')}
              className="p-4 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/50 rounded-[8px] text-left transition-all group cursor-pointer"
            >
              <div className="w-9 h-9 rounded-[6px] bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mb-3 group-hover:bg-blue-500/20 transition-colors">
                <UserPlus size={16} className="text-blue-400" />
              </div>
              <div className="text-sm font-medium text-[#F2F1EE] mb-1">Manual Hire</div>
              <p className="text-[10px] text-[#6B6B6E] font-mono leading-relaxed">
                Configure an agent from scratch with full control over role, model, and capabilities.
              </p>
            </button>

            {/* From Template */}
            <button
              onClick={() => setMode('template')}
              className="p-4 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/50 rounded-[8px] text-left transition-all group cursor-pointer"
            >
              <div className="w-9 h-9 rounded-[6px] bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center mb-3 group-hover:bg-emerald-500/20 transition-colors">
                <LayoutTemplate size={16} className="text-emerald-400" />
              </div>
              <div className="text-sm font-medium text-[#F2F1EE] mb-1">From Template</div>
              <p className="text-[10px] text-[#6B6B6E] font-mono leading-relaxed">
                Choose from 20 pre-built archetypes with capabilities, constraints, and system prompts.
              </p>
            </button>

            {/* Hire Team */}
            <button
              onClick={() => setMode('team')}
              className="p-4 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/50 rounded-[8px] text-left transition-all group cursor-pointer"
            >
              <div className="w-9 h-9 rounded-[6px] bg-purple-500/10 border border-purple-500/20 flex items-center justify-center mb-3 group-hover:bg-purple-500/20 transition-colors">
                <Users size={16} className="text-purple-400" />
              </div>
              <div className="text-sm font-medium text-[#F2F1EE] mb-1">Hire a Team</div>
              <p className="text-[10px] text-[#6B6B6E] font-mono leading-relaxed">
                Select multiple archetypes and deploy an entire squad in one batch operation.
              </p>
            </button>

            {/* Import Manifest */}
            <button
              onClick={() => setMode('manifest')}
              className="p-4 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/50 rounded-[8px] text-left transition-all group cursor-pointer"
            >
              <div className="w-9 h-9 rounded-[6px] bg-amber-500/10 border border-amber-500/20 flex items-center justify-center mb-3 group-hover:bg-amber-500/20 transition-colors">
                <FileJson size={16} className="text-amber-400" />
              </div>
              <div className="text-sm font-medium text-[#F2F1EE] mb-1">Import Manifest</div>
              <p className="text-[10px] text-[#6B6B6E] font-mono leading-relaxed">
                Deploy from a portable JSON manifest file (nexus/hire@1 spec).
              </p>
            </button>
          </div>

          {loadingMeta && (
            <p className="text-[10px] text-[#6B6B6E] font-mono text-center pt-2">
              Loading archetypes and providers...
            </p>
          )}
        </div>
      )}

      {/* Manual Hire Form */}
      {mode === 'manual' && (
        <form onSubmit={handleManualCreate} className="space-y-4">
          <button
            type="button"
            onClick={() => setMode('select')}
            className="flex items-center gap-1.5 text-[10px] font-mono text-[#6B6B6E] hover:text-[#FFB020] transition-colors cursor-pointer"
          >
            <ArrowLeft size={12} />
            Back to options
          </button>

          {error && (
            <div className="p-2.5 bg-red-500/10 border border-red-500/20 rounded-[6px] text-xs text-red-400 font-mono">
              {error}
            </div>
          )}

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Agent Call Sign / Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Helix-10"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="relative">
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Provider / Backend
              </label>
              <button
                type="button"
                onClick={() => setShowProviderMenu(!showProviderMenu)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] text-left flex items-center gap-2 cursor-pointer"
              >
                <span className={`w-2 h-2 rounded-full shrink-0 ${providers.find((p) => p.id === provider)?.installed ? 'bg-emerald-400' : 'bg-gray-500/50'}`} />
                <span className="flex-1 truncate">{providers.find((p) => p.id === provider)?.label || provider}</span>
                <svg className="w-3 h-3 text-[#6B6B6E]" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" /></svg>
              </button>
              {providers.find((p) => p.id === provider)?.installed && (
                <span className="text-[9px] font-mono text-emerald-400 flex items-center gap-1 mt-0.5">
                  <Circle size={6} className="fill-emerald-400 text-emerald-400" />
                  Installed & available on PATH
                </span>
              )}
              {showProviderMenu && (
                <>
                  <div className="fixed inset-0 z-40" onClick={() => setShowProviderMenu(false)} />
                  <div className="absolute z-50 mt-1 w-full bg-[#1C1C1F] border border-white/[0.14] rounded-[8px] shadow-2xl overflow-hidden">
                    <div className="max-h-52 overflow-y-auto py-1">
                      {providers.map((p) => (
                        <button
                          key={p.id}
                          type="button"
                          onClick={() => { setProvider(p.id); setModel(''); setShowProviderMenu(false); }}
                          className={`w-full px-3 py-2 text-left text-xs flex items-center gap-2.5 transition-colors cursor-pointer ${provider === p.id
                            ? 'bg-[#FFB020]/10 text-[#FFB020]'
                            : 'text-[#F2F1EE] hover:bg-white/[0.06]'
                            }`}
                        >
                          <span className={`w-2 h-2 rounded-full shrink-0 ${p.installed ? 'bg-emerald-400 shadow-[0_0_4px_rgba(52,211,153,0.5)]' : 'bg-gray-600 border border-gray-500'}`} />
                          <span className="flex-1">{p.label}</span>
                          {p.installed && <span className="text-[9px] text-emerald-400/70 font-mono">ready</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                </>
              )}
            </div>

            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Model Engine
              </label>
              {providerModels.length > 0 ? (
                <>
                  <select
                    value={model}
                    onChange={(e) => {
                      if (e.target.value === '__custom__') {
                        setModel('');
                        setProviderModels([]);
                      } else {
                        setModel(e.target.value);
                      }
                    }}
                    className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                  >
                    <option value="">Provider default (recommended)</option>
                    {providerModels.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name} ({m.tier})
                      </option>
                    ))}
                    <option value="__custom__">✎ Enter custom model ID...</option>
                  </select>
                  <span className="text-[9px] font-mono text-[#6B6B6E] mt-0.5 block">
                    {!model ? `No override — ${providers.find((p) => p.id === provider)?.label || provider} will use its configured default` : `Override: ${model}`}
                  </span>
                </>
              ) : (
                <>
                  <input
                    type="text"
                    value={model}
                    onChange={(e) => setModel(e.target.value)}
                    placeholder="Leave empty for provider default"
                    className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                  />
                  <button
                    type="button"
                    onClick={() => setProviderModels(FALLBACK_MODELS[provider] || [])}
                    className="text-[9px] font-mono text-[#6B6B6E] hover:text-[#FFB020] mt-0.5 cursor-pointer"
                  >
                    ← Back to model list
                  </button>
                </>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Role Classification
              </label>
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="">Select role...</option>
                {archetypes.length > 0 ? (
                  archetypes.map((a) => (
                    <option key={a.role} value={a.role}>
                      {a.name}
                    </option>
                  ))
                ) : (
                  <>
                    <option value="backend-engineer">Backend Engineer</option>
                    <option value="frontend-engineer">Frontend Engineer</option>
                    <option value="software-architect">Software Architect</option>
                    <option value="devops-engineer">DevOps Engineer</option>
                    <option value="qa-engineer">QA Engineer</option>
                    <option value="security-engineer">Security Engineer</option>
                    <option value="ml-engineer">ML Engineer</option>
                    <option value="product-manager">Product Manager</option>
                    <option value="researcher">Researcher</option>
                    <option value="designer">Designer</option>
                  </>
                )}
              </select>
            </div>

            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Title / Specialization
              </label>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="e.g. Distributed Consensus Architect"
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Capabilities (comma-separated)
            </label>
            <input
              type="text"
              value={capabilities}
              onChange={(e) => setCapabilities(e.target.value)}
              placeholder="e.g. api-design, database-modeling, performance-tuning"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Primary Responsibilities
            </label>
            <textarea
              value={responsibilities}
              onChange={(e) => setResponsibilities(e.target.value)}
              placeholder="Describe core operational goals"
              rows={2}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Objectives
            </label>
            <input
              type="text"
              value={objectives}
              onChange={(e) => setObjectives(e.target.value)}
              placeholder="e.g. Sub-millisecond API responses"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <details className="group">
            <summary className="text-[10px] font-mono text-[#6B6B6E] cursor-pointer hover:text-[#FFB020] transition-colors">
              Advanced: Personality & Identity
            </summary>
            <div className="mt-3 space-y-3 pl-2 border-l border-white/[0.06]">
              {/* Soul Template Quick-Fill */}
              {soulTemplates.length > 0 && (
                <div>
                  <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                    Pre-fill from Soul Template
                  </label>
                  <div className="flex flex-wrap gap-1.5">
                    {soulTemplates.map((st) => (
                      <button
                        key={st.template_id}
                        type="button"
                        onClick={() => {
                          setPersonalityTraits(st.soul.personality_traits.join(', '));
                          setCommunicationStyle(st.soul.communication_style);
                          setAgentValues(st.soul.values.join(', '));
                          setAgentConstraints(st.soul.constraints.join('\n'));
                          setTone(st.soul.tone);
                          setSoulDescription(st.soul.background);
                        }}
                        className="px-2 py-1 bg-[#101012] border border-white/[0.08] hover:border-[#FFB020]/30 rounded-[4px] text-[10px] font-mono text-[#A8A8AB] hover:text-[#FFB020] transition-colors cursor-pointer"
                      >
                        {st.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Personality Traits */}
              <div>
                <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                  Personality Traits (comma-separated)
                </label>
                <input
                  type="text"
                  value={personalityTraits}
                  onChange={(e) => setPersonalityTraits(e.target.value)}
                  placeholder="e.g. detail-oriented, methodical, pragmatic, collaborative"
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              {/* Communication Style */}
              <div>
                <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                  Communication Style
                </label>
                <textarea
                  value={communicationStyle}
                  onChange={(e) => setCommunicationStyle(e.target.value)}
                  placeholder="How this agent communicates (e.g. 'Concise and technical. Prefers code examples over lengthy explanations.')"
                  rows={2}
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                {/* Values */}
                <div>
                  <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                    Core Values (comma-separated)
                  </label>
                  <input
                    type="text"
                    value={agentValues}
                    onChange={(e) => setAgentValues(e.target.value)}
                    placeholder="code quality, maintainability..."
                    className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                  />
                </div>

                {/* Tone */}
                <div>
                  <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                    Tone
                  </label>
                  <select
                    value={tone}
                    onChange={(e) => setTone(e.target.value)}
                    className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                  >
                    <option value="professional">Professional</option>
                    <option value="casual">Casual</option>
                    <option value="formal">Formal</option>
                    <option value="friendly">Friendly</option>
                    <option value="direct">Direct</option>
                  </select>
                </div>
              </div>

              {/* Constraints */}
              <div>
                <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                  Behavioral Constraints (one per line)
                </label>
                <textarea
                  value={agentConstraints}
                  onChange={(e) => setAgentConstraints(e.target.value)}
                  placeholder={"Always write tests for new functionality\nFollow existing codebase conventions\nPrefer simple solutions over clever ones"}
                  rows={3}
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              {/* Soul Description / Background */}
              <div>
                <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                  Background / Soul Description
                </label>
                <textarea
                  value={soulDescription}
                  onChange={(e) => setSoulDescription(e.target.value)}
                  placeholder="Agent background narrative and behavioral instructions..."
                  rows={2}
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              {/* Budget */}
              <div>
                <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                  Monthly Budget (USD)
                </label>
                <input
                  type="number"
                  value={budgetCents ? budgetCents / 100 : ''}
                  onChange={(e) => setBudgetCents(Math.round(parseFloat(e.target.value || '0') * 100))}
                  placeholder="e.g. 300"
                  min={0}
                  step={10}
                  className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
                />
              </div>
            </div>
          </details>

          <div className="flex justify-end gap-2 pt-3 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={onClose}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit" loading={creating}>
              Deploy Agent
            </Button>
          </div>
        </form>
      )}

      {/* Template Selection */}
      {mode === 'template' && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMode('select')}
            className="flex items-center gap-1.5 text-[10px] font-mono text-[#6B6B6E] hover:text-[#FFB020] transition-colors cursor-pointer"
          >
            <ArrowLeft size={12} />
            Back to options
          </button>

          <p className="text-xs text-[#9C9C9F] font-mono">
            Select an archetype to pre-fill the agent configuration. You can customize before deploying.
          </p>

          <ArchetypeGrid archetypes={archetypes} onSelect={handleTemplateSelect} />
        </div>
      )}

      {/* Team Hire Flow */}
      {mode === 'team' && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMode('select')}
            className="flex items-center gap-1.5 text-[10px] font-mono text-[#6B6B6E] hover:text-[#FFB020] transition-colors cursor-pointer"
          >
            <ArrowLeft size={12} />
            Back to options
          </button>

          <TeamHireFlow
            archetypes={archetypes}
            providers={providers}
            onSuccess={onSuccess}
            onCancel={onClose}
          />
        </div>
      )}

      {/* Manifest Import */}
      {mode === 'manifest' && (
        <div className="space-y-4">
          <button
            type="button"
            onClick={() => setMode('select')}
            className="flex items-center gap-1.5 text-[10px] font-mono text-[#6B6B6E] hover:text-[#FFB020] transition-colors cursor-pointer"
          >
            <ArrowLeft size={12} />
            Back to options
          </button>

          <ManifestImport onSuccess={onSuccess} onCancel={onClose} />
        </div>
      )}
    </Modal>
  );
}
