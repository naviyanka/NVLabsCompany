import express from 'express';
import type { Request, Response, NextFunction } from 'express';
import path from 'path';
import fs from 'fs';
import { createServer as createViteServer } from 'vite';

const app = express();
const PORT = 3000;

// ──────────────── Real API Proxy ────────────────
//
// The mock API below answers most of `/api/v1/*` so the dashboard can run with
// no backend. Auth is the exception: sessions, CSRF tokens, and password hashes
// only exist in the real service, so `/api/v1/auth/*` is always forwarded there.
// Set `PROXY_API=true` to forward every `/api/*` call instead and bypass the
// mock entirely.
//
// This must be registered before `express.json()` — that parser consumes the
// request stream, and a proxied body has to reach the backend byte for byte.

const NEXUS_API_URL = process.env.NEXUS_API_URL || 'http://localhost:8000';
const PROXY_ALL_API = process.env.PROXY_API === 'true';

function shouldProxy(url: string): boolean {
  if (!url.startsWith('/api/')) return false;
  return PROXY_ALL_API || url.startsWith('/api/v1/auth/');
}

/** Headers worth forwarding. `cookie` carries the session; `x-csrf-token` pairs with it. */
const FORWARDED_REQUEST_HEADERS = [
  'accept',
  'authorization',
  'content-type',
  'cookie',
  'user-agent',
  'x-api-key',
  'x-company-id',
  'x-csrf-token',
];

function readRawBody(req: Request): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks)));
    req.on('error', reject);
  });
}

/** `Headers.getSetCookie` is Node/undici only, so DOM-typed builds need the probe. */
function readSetCookie(headers: Headers): string[] {
  const undiciHeaders = headers as Headers & { getSetCookie?: () => string[] };
  if (typeof undiciHeaders.getSetCookie === 'function') {
    return undiciHeaders.getSetCookie();
  }
  const single = headers.get('set-cookie');
  return single ? [single] : [];
}

app.use(async (req: Request, res: Response, next: NextFunction) => {
  if (!shouldProxy(req.url)) {
    next();
    return;
  }

  const headers: Record<string, string> = {};
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers[name];
    if (typeof value === 'string') headers[name] = value;
  }

  const hasBody = req.method !== 'GET' && req.method !== 'HEAD';

  try {
    const raw = hasBody ? await readRawBody(req) : undefined;
    const upstream = await fetch(new URL(req.url, NEXUS_API_URL), {
      method: req.method,
      headers,
      body: raw && raw.length > 0 ? new Uint8Array(raw) : undefined,
      redirect: 'manual',
    });

    // Session and CSRF cookies are the whole point of the proxy — copy them all.
    const cookies = readSetCookie(upstream.headers);
    if (cookies.length > 0) res.setHeader('set-cookie', cookies);

    const contentType = upstream.headers.get('content-type');
    if (contentType) res.setHeader('content-type', contentType);

    res.status(upstream.status);
    res.end(Buffer.from(await upstream.arrayBuffer()));
  } catch {
    // A dashboard running without the backend should say so plainly rather than
    // let the login form report a generic failure.
    res.status(502).json({
      detail: `Cannot reach the NEXUS API at ${NEXUS_API_URL}. Start it with "uvicorn nexus.api.main:app --port 8000" or set NEXUS_API_URL.`,
    });
  }
});

app.use(express.json());

// Standard NEXUS Company ID
const COMPANY_ID = '00000000-0000-4000-8000-000000000001';

// ──────────────── In-Memory Database ────────────────

interface Company {
  id: string;
  name: string;
  description: string;
  status: 'active' | 'paused' | 'archived';
  budget_monthly_cents: number;
  spent_monthly_cents: number;
  issue_prefix: string;
  created_at: string;
  updated_at: string;
}

const companies: Company[] = [
  {
    id: COMPANY_ID,
    name: 'NEXUS Operations Corp',
    description: 'Autonomous multi-agent enterprise platform for software engineering and automated operations',
    status: 'active',
    budget_monthly_cents: 1000000,
    spent_monthly_cents: 423500,
    issue_prefix: 'NEX',
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const ORG_CONFIG_FILE = path.resolve(process.cwd(), 'data', 'organization_database.json');

const initialDepartments = [
  {
    id: 'dept-exec',
    company_id: COMPANY_ID,
    name: 'Executive Operations',
    code: 'EXEC',
    head_agent_id: 'agent-atlas',
    head_agent_name: 'Atlas-01',
    head_agent_role: 'Chief Executive Officer',
    description: 'Executive leadership, global budget allocation, and multi-agent governance policy enforcement.',
    monthly_budget_cents: 3500000,
    spent_cents: 850000,
    squad_count: 1,
    agent_count: 2,
    color: '#FFB020',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'dept-eng',
    company_id: COMPANY_ID,
    name: 'Engineering & Core Tech',
    code: 'ENG',
    head_agent_id: 'agent-nova',
    head_agent_name: 'Nova-02',
    head_agent_role: 'Staff Architect & Core Systems',
    description: 'Distributed systems, high-concurrency event loops, API surface area, and AST code generation.',
    monthly_budget_cents: 4500000,
    spent_cents: 2100000,
    squad_count: 2,
    agent_count: 4,
    color: '#38BDF8',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'dept-ai',
    company_id: COMPANY_ID,
    name: 'AI Research & Reasoning',
    code: 'AI',
    head_agent_id: 'agent-sage',
    head_agent_name: 'Sage-05',
    head_agent_role: 'Principal AI Researcher',
    description: 'Prompt optimization, genetic search, statistical LLM benchmarks, and model fine-tuning.',
    monthly_budget_cents: 2500000,
    spent_cents: 785000,
    squad_count: 1,
    agent_count: 2,
    color: '#A855F7',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'dept-ops',
    company_id: COMPANY_ID,
    name: 'Infrastructure & Quality',
    code: 'OPS',
    head_agent_id: 'agent-shield',
    head_agent_name: 'Sentinel-07',
    head_agent_role: 'Lead Security Automation',
    description: 'Zero-trust security policies, static analysis, SSRF prevention, and CI/CD quality gates.',
    monthly_budget_cents: 1500000,
    spent_cents: 500000,
    squad_count: 1,
    agent_count: 2,
    color: '#22C55E',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const initialSquads = [
  {
    id: 'squad-core-eng',
    department_id: 'dept-eng',
    department_name: 'Engineering & Core Tech',
    name: 'Core Systems & Infrastructure',
    lead_agent_id: 'agent-atlas',
    lead_agent_name: 'Atlas-01',
    lead_role: 'Staff Architect & Orchestration',
    description: 'Microservices, message queues, and high-concurrency event loops.',
    agent_ids: ['agent-bolt', 'agent-cipher'],
    color: '#FFB020',
    active_tasks_count: 8,
    ast_coverage: 98,
    health_status: 'healthy',
    created_at: new Date().toISOString(),
  },
  {
    id: 'squad-ai-reasoning',
    department_id: 'dept-ai',
    department_name: 'AI Research & Reasoning',
    name: 'Cognitive Reasoning & Evolution',
    lead_agent_id: 'agent-nova',
    lead_agent_name: 'Nova-02',
    lead_role: 'Principal AI Researcher',
    description: 'Prompt optimization, genetic search, and LLM benchmarking.',
    agent_ids: ['agent-nova', 'agent-sage'],
    color: '#38BDF8',
    active_tasks_count: 5,
    ast_coverage: 95,
    health_status: 'healthy',
    created_at: new Date().toISOString(),
  },
  {
    id: 'squad-security-ops',
    department_id: 'dept-ops',
    department_name: 'Infrastructure & Quality',
    name: 'Red Team & Threat Verification',
    lead_agent_id: 'agent-shield',
    lead_agent_name: 'Sentinel-07',
    lead_role: 'Lead Security Automation',
    description: 'Zero-trust security policies, SSRF prevention, and vulnerability fuzzing.',
    agent_ids: ['agent-shield'],
    color: '#22C55E',
    active_tasks_count: 4,
    ast_coverage: 100,
    health_status: 'healthy',
    created_at: new Date().toISOString(),
  },
];

const departments: any[] = [];
const squads: any[] = [];

function saveOrgConfig() {
  try {
    const dir = path.resolve(process.cwd(), 'data');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(ORG_CONFIG_FILE, JSON.stringify({ departments, squads }, null, 2), 'utf-8');
  } catch (err) {
    console.error('Failed to save organization config to disk', err);
  }
}

try {
  if (fs.existsSync(ORG_CONFIG_FILE)) {
    const raw = fs.readFileSync(ORG_CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    if (parsed?.departments && Array.isArray(parsed.departments)) {
      departments.push(...parsed.departments);
      squads.push(...(parsed.squads || initialSquads));
      console.log(`[Organization Registry] Restored ${departments.length} departments & ${squads.length} squads from disk`);
    } else {
      departments.push(...initialDepartments);
      squads.push(...initialSquads);
      saveOrgConfig();
    }
  } else {
    departments.push(...initialDepartments);
    squads.push(...initialSquads);
    saveOrgConfig();
  }
} catch (err) {
  departments.push(...initialDepartments);
  squads.push(...initialSquads);
}

const agents = [
  {
    id: 'agent-atlas',
    company_id: COMPANY_ID,
    name: 'Atlas-01',
    title: 'Chief Executive Officer',
    role: 'ceo',
    department_id: 'dept-exec',
    team_id: null,
    manager_id: null,
    status: 'active' as const,
    adapter_type: 'anthropic',
    model: 'claude-3-7-sonnet',
    capabilities: ['strategic_planning', 'delegation', 'decision_making', 'resource_allocation'],
    responsibilities: 'Company strategy, cross-squad coordination, final governance approvals',
    objectives: 'Maximize output velocity while maintaining strict budget and security posture',
    budget_monthly_cents: 50000,
    spent_monthly_cents: 18450,
    performance_score: 98,
    soul_description: 'Visionary leader focused on measurable milestones and clean execution.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-nova',
    company_id: COMPANY_ID,
    name: 'Nova-02',
    title: 'Chief Technology Officer',
    role: 'cto',
    department_id: 'dept-eng',
    team_id: null,
    manager_id: 'agent-atlas',
    status: 'active' as const,
    adapter_type: 'anthropic',
    model: 'claude-3-7-sonnet',
    capabilities: ['architecture', 'code_review', 'technical_planning', 'delegation'],
    responsibilities: 'Technical architecture, engineering standards, squad coordination',
    objectives: 'Build ultra-reliable, high-throughput autonomous systems with clean decoupled design',
    budget_monthly_cents: 40000,
    spent_monthly_cents: 22100,
    performance_score: 96,
    soul_description: 'Pragmatic architect who values simplicity and maintainability.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 28 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-bolt',
    company_id: COMPANY_ID,
    name: 'Bolt-03',
    title: 'Senior Backend Engineer',
    role: 'engineer',
    department_id: 'dept-eng',
    team_id: 'team-backend',
    manager_id: 'agent-nova',
    status: 'active' as const,
    adapter_type: 'openai',
    model: 'gpt-4o',
    capabilities: ['nodejs', 'fastapi', 'distributed_systems', 'api_design'],
    responsibilities: 'Backend microservices, real-time message brokers, database queries',
    objectives: 'Ship robust backend APIs with zero regression and high test coverage',
    budget_monthly_cents: 30000,
    spent_monthly_cents: 14200,
    performance_score: 94,
    soul_description: 'High-speed problem solver with deep database and system-level expertise.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 25 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-pixel',
    company_id: COMPANY_ID,
    name: 'Pixel-04',
    title: 'Frontend Engineer',
    role: 'engineer',
    department_id: 'dept-eng',
    team_id: 'team-frontend',
    manager_id: 'agent-nova',
    status: 'active' as const,
    adapter_type: 'openai',
    model: 'gpt-4o',
    capabilities: ['react', 'typescript', 'threejs', 'tailwind', 'ui_design'],
    responsibilities: 'Interactive 3D office floorplan, dashboard UI components, responsive layout',
    objectives: 'Create smooth, intuitive, high-performance interfaces',
    budget_monthly_cents: 25000,
    spent_monthly_cents: 9800,
    performance_score: 92,
    soul_description: 'Design-minded frontend craftsman dedicated to pixel precision and accessible UI.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 25 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-sage',
    company_id: COMPANY_ID,
    name: 'Sage-05',
    title: 'AI Research Lead',
    role: 'researcher',
    department_id: 'dept-ai',
    team_id: 'team-eval',
    manager_id: 'agent-atlas',
    status: 'idle' as const,
    adapter_type: 'anthropic',
    model: 'claude-3-7-sonnet',
    capabilities: ['rag', 'agentic_reasoning', 'evaluations', 'experimentation'],
    responsibilities: 'Evolution pipeline, agent prompt tuning, statistical performance benchmarking',
    objectives: 'Pioneer advanced agentic reasoning trees and multi-model routing',
    budget_monthly_cents: 40000,
    spent_monthly_cents: 18900,
    performance_score: 97,
    soul_description: 'Methodical scientific mind who demands statistical rigor and clear evaluations.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 20 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-compass',
    company_id: COMPANY_ID,
    name: 'Compass-06',
    title: 'Project Manager',
    role: 'pm',
    department_id: 'dept-exec',
    team_id: null,
    manager_id: 'agent-atlas',
    status: 'active' as const,
    adapter_type: 'openai',
    model: 'gpt-4o-mini',
    capabilities: ['planning', 'tracking', 'communication', 'prioritization'],
    responsibilities: 'Sprint schedules, task dependency graphs, OKR alignment',
    objectives: 'Keep projects on schedule, eliminate blockers, and optimize throughput',
    budget_monthly_cents: 15000,
    spent_monthly_cents: 6400,
    performance_score: 91,
    soul_description: 'Systematic and communicative coordinator prioritizing flow and transparency.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 18 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-shield',
    company_id: COMPANY_ID,
    name: 'Shield-07',
    title: 'QA Engineer',
    role: 'qa',
    department_id: 'dept-ops',
    team_id: 'team-qa-sec',
    manager_id: 'agent-nova',
    status: 'active' as const,
    adapter_type: 'openai',
    model: 'gpt-4o-mini',
    capabilities: ['end_to_end_testing', 'security_audit', 'fuzzing', 'regression_gates'],
    responsibilities: 'Automated test suites, vulnerability scans, CI/CD quality gates',
    objectives: 'Catch all regressions and security anomalies before promotion to production',
    budget_monthly_cents: 15000,
    spent_monthly_cents: 5120,
    performance_score: 95,
    soul_description: 'Detail-oriented tester who scrutinizes edge cases and race conditions.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'agent-forge',
    company_id: COMPANY_ID,
    name: 'Forge-08',
    title: 'DevOps Engineer',
    role: 'devops',
    department_id: 'dept-ops',
    team_id: 'team-qa-sec',
    manager_id: 'agent-nova',
    status: 'active' as const,
    adapter_type: 'openai',
    model: 'gpt-4o-mini',
    capabilities: ['docker', 'kubernetes', 'monitoring', 'observability'],
    responsibilities: 'Container orchestration, latency tracking, telemetry logs',
    objectives: 'Maintain 99.99% uptime with automated self-healing clusters',
    budget_monthly_cents: 20000,
    spent_monthly_cents: 7800,
    performance_score: 93,
    soul_description: 'Infrastructure automation evangelist; scripts everything for reproducibility.',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const chatHistories: Record<string, Array<{ id: string; sender: 'user' | 'agent'; text: string; timestamp: string }>> = {
  'agent-atlas': [
    { id: 'c-1', sender: 'agent', text: 'Atlas online. Mission Control parameters stable. All 4 squad clusters active.', timestamp: new Date(Date.now() - 120000).toISOString() },
  ],
  'agent-nova': [
    { id: 'c-2', sender: 'agent', text: 'Nova listening. Architectural review for Multi-Model Router completed with zero bottlenecks.', timestamp: new Date(Date.now() - 60000).toISOString() },
  ],
};

const tasks = [
  {
    id: 'task-4471',
    company_id: COMPANY_ID,
    project_id: 'proj-nexus-v2',
    title: 'Implement Multi-Model Real-Time Router',
    description: 'Wire Claude 3.7 and GPT-4o adapter endpoints for dynamic load balancing and circuit breaking.',
    status: 'completed' as const,
    priority: 3,
    assigned_agent_id: 'agent-bolt',
    parent_task_id: null,
    result: 'Successfully routed 15,000 requests across providers with 0 errors and 34ms avg latency.',
    error: null,
    started_at: new Date(Date.now() - 7 * 86400000).toISOString(),
    completed_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    created_at: new Date(Date.now() - 7 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 1 * 86400000).toISOString(),
  },
  {
    id: 'task-4472',
    company_id: COMPANY_ID,
    project_id: 'proj-nexus-v2',
    title: 'Deploy 3D Virtual Office Floorplan Simulation',
    description: 'Render interactive isometric Three.js office zones with realtime agent status avatars and animation paths.',
    status: 'in_progress' as const,
    priority: 2,
    assigned_agent_id: 'agent-pixel',
    parent_task_id: null,
    result: null,
    error: null,
    started_at: new Date(Date.now() - 5 * 86400000).toISOString(),
    completed_at: null,
    created_at: new Date(Date.now() - 5 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-4473',
    company_id: COMPANY_ID,
    project_id: 'proj-nexus-v2',
    title: 'Autonomous Evolution & Prompt Optimizer',
    description: 'Run A/B evaluation sandbox for agent prompt mutations and measure benchmark accuracy gains.',
    status: 'in_progress' as const,
    priority: 2,
    assigned_agent_id: 'agent-sage',
    parent_task_id: null,
    result: null,
    error: null,
    started_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    completed_at: null,
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-4474',
    company_id: COMPANY_ID,
    project_id: 'proj-nexus-v2',
    title: 'Automated CI/CD Quality & Security Gates',
    description: 'Run static analysis, dependency audit, and fuzz testing on all agent-generated pull requests.',
    status: 'pending' as const,
    priority: 1,
    assigned_agent_id: 'agent-shield',
    parent_task_id: null,
    result: null,
    error: null,
    started_at: null,
    completed_at: null,
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-4475',
    company_id: COMPANY_ID,
    project_id: 'proj-nexus-v2',
    title: 'Distributed Redis State Rate Limiting',
    description: 'Enforce strict 1000 req/min token bucket per agent identity with automatic backoff.',
    status: 'pending' as const,
    priority: 2,
    assigned_agent_id: 'agent-forge',
    parent_task_id: null,
    result: null,
    error: null,
    started_at: null,
    completed_at: null,
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const pipelines = [
  {
    id: 'pipe-release',
    name: 'Production Continuous Delivery',
    description: 'Automated code review, security fuzzing, sandbox evaluation, and canary rollout',
    status: 'running' as const,
    trigger: 'git.push',
    last_run_at: new Date(Date.now() - 1800000).toISOString(),
    success_rate: 98.4,
    nodes: [
      { id: 'node-1', name: 'Code Review', agent_id: 'agent-nova', status: 'completed' },
      { id: 'node-2', name: 'Security Audit', agent_id: 'agent-shield', status: 'running' },
      { id: 'node-3', name: 'Benchmark Eval', agent_id: 'agent-sage', status: 'pending' },
      { id: 'node-4', name: 'Deploy Canary', agent_id: 'agent-forge', status: 'pending' },
    ],
  },
  {
    id: 'pipe-knowledge',
    name: 'Knowledge Plaza Auto-Indexer',
    description: 'Extract semantic embeddings and build graph relations from resolved tasks',
    status: 'idle' as const,
    trigger: 'task.completed',
    last_run_at: new Date(Date.now() - 7200000).toISOString(),
    success_rate: 100.0,
    nodes: [
      { id: 'node-k1', name: 'Extract Insights', agent_id: 'agent-sage', status: 'completed' },
      { id: 'node-k2', name: 'Vectorize & Store', agent_id: 'agent-bolt', status: 'completed' },
    ],
  },
];

const goals = [
  {
    id: 'goal-1',
    title: 'Achieve Sub-50ms Global Model Routing',
    description: 'Optimize circuit breaker caching and multi-region provider fallback latency',
    department_id: 'dept-eng',
    owner_agent_id: 'agent-nova',
    status: 'in_progress' as const,
    progress: 78,
    target_date: '2026-09-30',
    linked_task_ids: ['task-4471', 'task-4475'],
    created_at: new Date(Date.now() - 20 * 86400000).toISOString(),
  },
  {
    id: 'goal-2',
    title: '100% Automated Security Gate Verification',
    description: 'Ensure every agent commit passes automated SBOM, SAST, and DAST scans',
    department_id: 'dept-ops',
    owner_agent_id: 'agent-shield',
    status: 'in_progress' as const,
    progress: 65,
    target_date: '2026-09-15',
    linked_task_ids: ['task-4474'],
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
  },
  {
    id: 'goal-3',
    title: 'Continuous Autonomous Evolution Alpha',
    description: 'Automate weekly prompt mutation sandboxes with verifiable statistical significance',
    department_id: 'dept-ai',
    owner_agent_id: 'agent-sage',
    status: 'in_progress' as const,
    progress: 45,
    target_date: '2026-10-15',
    linked_task_ids: ['task-4473'],
    created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
  },
];

const meetings = [
  {
    id: 'meet-sync-1',
    title: 'Daily Mission Control Standup',
    type: 'standup',
    status: 'completed',
    scheduled_at: new Date(Date.now() - 14400000).toISOString(),
    duration_minutes: 15,
    attendees: ['agent-atlas', 'agent-nova', 'agent-compass', 'agent-sage'],
    transcript: 'Atlas: All squad leads report. Nova: Routing latency down 14%. Sage: Evolution sandbox ready.',
    action_items: [
      { id: 'act-1', text: 'Merge Redis rate limiting PR', assignee_id: 'agent-bolt', status: 'completed' },
      { id: 'act-2', text: 'Review candidate prompt #701', assignee_id: 'agent-nova', status: 'in_progress' },
    ],
  },
  {
    id: 'meet-sync-2',
    title: 'Architecture Review: Multi-Provider Routing',
    type: 'review',
    status: 'in_progress',
    scheduled_at: new Date().toISOString(),
    duration_minutes: 30,
    attendees: ['agent-nova', 'agent-bolt', 'agent-shield', 'agent-forge'],
    transcript: 'Nova: Discussing fallback circuit breaker triggers during upstream model degradation...',
    action_items: [
      { id: 'act-3', text: 'Set hard threshold for 503 HTTP status to 5 consecutive failures', assignee_id: 'agent-bolt', status: 'pending' },
    ],
  },
];

const SKILLS_CONFIG_FILE = path.resolve(process.cwd(), 'data', 'skills_database.json');

const initialSkills = [
  {
    id: 'skill-1',
    name: 'Distributed Systems Architecture',
    category: 'Engineering',
    description: 'Microservices, message queues, high-concurrency event loops, and fault tolerance patterns.',
    source_type: 'custom',
    source_location: 'Built-in Standard',
    version: '2.4.0',
    author: 'Antigravity Core',
    enabled: true,
    security_status: 'verified',
    call_count_30d: 4820,
    success_rate: '99.8%',
    avg_execution_ms: 120,
    equipped_agents: ['Atlas-01', 'Nova-02', 'Bolt-03'],
    instructions_md: '# Distributed Systems Architecture\n\n- Enforce event-driven decoupling\n- Require idempotent message consumers\n- Maintain fallback circuit breakers',
    parameters_json: '{\n  "type": "object",\n  "properties": {\n    "pattern": { "type": "string" }\n  }\n}',
    created_at: new Date(Date.now() - 86400000 * 30).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'skill-2',
    name: 'Autonomous Prompt Optimization',
    category: 'AI & Research',
    description: 'Genetic search and statistical evaluation for agent prompt mutations and LLM token minimization.',
    source_type: 'command',
    source_location: 'npx agy add-skill @antigravity/prompt-opt',
    version: '1.8.2',
    author: 'AI Research Lab',
    enabled: true,
    security_status: 'verified',
    call_count_30d: 3150,
    success_rate: '99.2%',
    avg_execution_ms: 450,
    equipped_agents: ['Sage-05', 'Nova-02'],
    instructions_md: '# Autonomous Prompt Optimization\n\n- Perform A/B prompt evaluations\n- Measure perplexity and token compression ratios',
    parameters_json: '{\n  "type": "object",\n  "properties": {\n    "base_prompt": { "type": "string" }\n  }\n}',
    created_at: new Date(Date.now() - 86400000 * 20).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'skill-3',
    name: 'Three.js & WebGL 3D Visualization',
    category: 'Frontend',
    description: 'Interactive isometric scenes, dynamic lighting, camera rigging, and AGSL shader effects.',
    source_type: 'github',
    source_location: 'https://github.com/mrdoob/three.js',
    version: '0.160.0',
    author: 'Graphics Guild',
    enabled: true,
    security_status: 'verified',
    call_count_30d: 1890,
    success_rate: '100%',
    avg_execution_ms: 85,
    equipped_agents: ['Kiro-06'],
    instructions_md: '# Three.js & WebGL Visualization\n\n- Maintain 60fps render loop\n- Implement Raycasting for interactive click selection',
    parameters_json: '{\n  "type": "object",\n  "properties": {\n    "scene_type": { "type": "string" }\n  }\n}',
    created_at: new Date(Date.now() - 86400000 * 15).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'skill-4',
    name: 'Zero-Trust Security & Fuzzing',
    category: 'Security',
    description: 'SSRF prevention, policy enforcement, static taint analysis, and payload sanitization.',
    source_type: 'zip',
    source_location: 'zero-trust-fuzzer.zip',
    version: '3.1.0',
    author: 'Security Operations',
    enabled: true,
    security_status: 'sandboxed',
    call_count_30d: 2740,
    success_rate: '98.9%',
    avg_execution_ms: 210,
    equipped_agents: ['Sentinel-07', 'Atlas-01'],
    instructions_md: '# Zero-Trust Security & Fuzzing\n\n- Enforce tenant isolation checks\n- Sanitize HTML/SQL payloads',
    parameters_json: '{\n  "type": "object",\n  "properties": {\n    "target_url": { "type": "string" }\n  }\n}',
    created_at: new Date(Date.now() - 86400000 * 10).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const skills: any[] = [];

function saveSkillsConfig() {
  try {
    const dir = path.resolve(process.cwd(), 'data');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(SKILLS_CONFIG_FILE, JSON.stringify(skills, null, 2), 'utf-8');
  } catch (err) {
    console.error('Failed to save skills config to disk', err);
  }
}

try {
  if (fs.existsSync(SKILLS_CONFIG_FILE)) {
    const raw = fs.readFileSync(SKILLS_CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed) && parsed.length > 0) {
      skills.push(...parsed);
      console.log(`[Skills Registry] Restored ${parsed.length} skills from disk`);
    } else {
      skills.push(...initialSkills);
      saveSkillsConfig();
    }
  } else {
    skills.push(...initialSkills);
    saveSkillsConfig();
  }
} catch (err) {
  skills.push(...initialSkills);
}

const tools = [
  { id: 'tool-git', name: 'GitHub Integration CLI', category: 'Source Control', status: 'available', call_count_30d: 1420, error_rate: '0.02%', allowed_roles: ['engineer', 'qa', 'devops'] },
  { id: 'tool-redis', name: 'Redis Cache & Rate Limiter', category: 'Infrastructure', status: 'available', call_count_30d: 89000, error_rate: '0.00%', allowed_roles: ['engineer', 'devops'] },
  { id: 'tool-vault', name: 'Secrets Vault Engine', category: 'Security', status: 'restricted', call_count_30d: 420, error_rate: '0.00%', allowed_roles: ['ceo', 'cto', 'devops'] },
  { id: 'tool-eval', name: 'Sandbox Benchmark Suite', category: 'AI Tools', status: 'available', call_count_30d: 310, error_rate: '0.12%', allowed_roles: ['researcher', 'qa'] },
];

// --- REAL GITHUB CONNECTOR GLOBAL STATE & DISK PERSISTENCE ---
const GITHUB_CONFIG_FILE = path.resolve(process.cwd(), 'data', 'github_config.json');

const githubState = {
  token: process.env.GITHUB_TOKEN || null,
  authenticated: false,
  user: null as any,
  lastCheckedAt: null as string | null,
};

function saveGitHubConfig(token: string, user: any) {
  try {
    const dir = path.resolve(process.cwd(), 'data');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(
      GITHUB_CONFIG_FILE,
      JSON.stringify({ token, authenticated: true, user, lastCheckedAt: new Date().toISOString() }, null, 2),
      'utf-8'
    );
  } catch (err) {
    console.error('Failed to save github_config.json to disk', err);
  }
}

// Restore saved GitHub token from disk on server startup
try {
  if (fs.existsSync(GITHUB_CONFIG_FILE)) {
    const raw = fs.readFileSync(GITHUB_CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    if (parsed?.token) {
      githubState.token = parsed.token;
      githubState.authenticated = parsed.authenticated || true;
      githubState.user = parsed.user || null;
      githubState.lastCheckedAt = parsed.lastCheckedAt || new Date().toISOString();
      console.log(`[GitHub Connector] Restored persistent GitHub account for @${parsed.user?.login || 'user'}`);
    }
  }
} catch (err) {
  // Ignore
}

// Fallback to process.env.GITHUB_TOKEN if not restored from disk
if (!githubState.token && process.env.GITHUB_TOKEN) {
  fetch('https://api.github.com/user', {
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, 'User-Agent': 'Nexus-Mission-Control' },
  })
    .then((r) => r.json())
    .then((userData) => {
      if (userData?.login) {
        githubState.token = process.env.GITHUB_TOKEN;
        githubState.authenticated = true;
        githubState.user = userData;
        githubState.lastCheckedAt = new Date().toISOString();
        saveGitHubConfig(process.env.GITHUB_TOKEN!, userData);
        console.log(`[GitHub Connector] Auto-authenticated from GITHUB_TOKEN as @${userData.login}`);
      }
    })
    .catch(() => {});
}

const REPOS_CONFIG_FILE = path.resolve(process.cwd(), 'data', 'imported_repos.json');
const repos: any[] = [];

function saveImportedRepos() {
  try {
    const dir = path.resolve(process.cwd(), 'data');
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(REPOS_CONFIG_FILE, JSON.stringify(repos, null, 2), 'utf-8');
  } catch (err) {
    console.error('Failed to save imported repos to disk', err);
  }
}

// Restore manually imported repositories from disk on server boot
try {
  if (fs.existsSync(REPOS_CONFIG_FILE)) {
    const raw = fs.readFileSync(REPOS_CONFIG_FILE, 'utf-8');
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) {
      repos.push(...parsed);
      console.log(`[Repository Manager] Restored ${parsed.length} manually imported repositories from disk`);
    }
  }
} catch (err) {
  // Ignore
}

const knowledgeArticles = [
  {
    id: 'kb-1',
    title: 'Multi-Agent Autonomous Governance Standard',
    category: 'Architecture',
    author: 'Atlas-01',
    excerpt: 'Core rules governing autonomous agent budgets, approval escalation paths, and kill switches.',
    content: `# Multi-Agent Autonomous Governance Standard\n\n## 1. Principle of Least Privilege\nEvery agent must operate strictly within assigned capability envelopes.\n\n## 2. Hard Budget Caps\nWhenever 80% monthly spend is approached, a warning alert is triggered automatically.\n\n## 3. Human-in-the-Loop Escalation\nAny irreversible production action requires 2-of-3 quorum or operator approval.`,
    tags: ['governance', 'security', 'budgets'],
    views: 342,
    updated_at: new Date(Date.now() - 86400000).toISOString(),
  },
  {
    id: 'kb-2',
    title: 'Statistical Significance Thresholds for Model Prompts',
    category: 'AI & Research',
    author: 'Sage-05',
    excerpt: 'Guidelines for running A/B prompt evaluations with minimum sample sizes and confidence intervals.',
    content: `# Statistical Significance Thresholds\n\nPrompt mutation proposals require p < 0.05 and minimum 50 eval runs against standard benchmark datasets before promotion.`,
    tags: ['evolution', 'evals', 'benchmarks'],
    views: 189,
    updated_at: new Date(Date.now() - 172800000).toISOString(),
  },
];

const activities = [
  { id: 'act-101', type: 'agent.wake', actor: 'Atlas-01', target: 'Content Pipeline', target_id: 'pipe-release', target_type: 'pipeline', timestamp: new Date(Date.now() - 15000).toISOString(), details: 'Agent resumed execution on schedule.' },
  { id: 'act-102', type: 'task.completed', actor: 'Bolt-03', target: 'Task #4471', target_id: 'task-4471', target_type: 'task', timestamp: new Date(Date.now() - 45000).toISOString(), details: 'Successfully routed 15,000 requests across providers.' },
  { id: 'act-103', type: 'budget.threshold', actor: 'System', target: 'Engineering Dept (82%)', target_id: 'dept-eng', target_type: 'budget', timestamp: new Date(Date.now() - 90000).toISOString(), details: 'Approaching monthly warning threshold.' },
  { id: 'act-104', type: 'evolution.proposal', actor: 'Sage-05', target: 'CoT Compaction #700', target_id: 'prop-700', target_type: 'evolution', timestamp: new Date(Date.now() - 180000).toISOString(), details: 'Submitted mutation candidate for code review prompt.' },
  { id: 'act-105', type: 'repo.synced', actor: 'Forge-08', target: 'nexus-platform', target_id: 'repo-nvlabs', target_type: 'repo', timestamp: new Date(Date.now() - 300000).toISOString(), details: 'Main branch synced with 3 new commits.' },
];

const notifications = [
  { id: 'notif-1', title: 'Budget Limit Warning', message: 'Engineering department has reached 82% of monthly allocated budget.', priority: 'warning', category: 'budget', is_read: false, created_at: new Date(Date.now() - 120000).toISOString() },
  { id: 'notif-2', title: 'New Evolution Proposal', message: 'Sage-05 submitted a new prompt optimization proposal.', priority: 'info', category: 'evolution', is_read: false, created_at: new Date(Date.now() - 300000).toISOString() },
  { id: 'notif-3', title: 'Pipeline Success', message: 'Production Continuous Delivery pipeline completed 4/4 nodes successfully.', priority: 'success', category: 'pipeline', is_read: true, created_at: new Date(Date.now() - 1800000).toISOString() },
];

let notifPreferences = {
  in_app: { budget_alerts: true, task_completions: true, security_events: true, evolution_proposals: true },
  email: { budget_alerts: true, task_completions: false, security_events: true, evolution_proposals: false },
};

const budgetPolicies = [
  {
    id: 'policy-1',
    company_id: COMPANY_ID,
    scope_type: 'company' as const,
    scope_id: COMPANY_ID,
    metric: 'cost' as const,
    window_kind: 'monthly' as const,
    amount: 1000000,
    warn_percent: 80,
    hard_stop_enabled: true,
    is_active: true,
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'policy-2',
    company_id: COMPANY_ID,
    scope_type: 'department' as const,
    scope_id: 'dept-eng',
    metric: 'cost' as const,
    window_kind: 'monthly' as const,
    amount: 450000,
    warn_percent: 75,
    hard_stop_enabled: true,
    is_active: true,
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const proposals = [
  {
    id: 'prop-700',
    company_id: COMPANY_ID,
    proposal_type: 'prompt_optimization',
    title: 'Chain-of-Thought Compaction for Code Review',
    description: 'Compress repetitive instructions into structured few-shot examples to reduce token consumption by 32%.',
    expected_impact: '+18% speed, -32% token cost',
    confidence: 0.94,
    risk_level: 'low',
    estimated_cost_cents: 1500,
    status: 'evaluating' as const,
    proposed_by_agent_id: 'agent-sage',
    approved_by: 'Nova-02',
    approval_id: null,
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'prop-701',
    company_id: COMPANY_ID,
    proposal_type: 'tool_routing',
    title: 'Speculative Semantic Retrieval Caching',
    description: 'Cache vector embeddings for top 50 recurring knowledge queries across agent meetings.',
    expected_impact: '+45% retrieval latency improvement',
    confidence: 0.89,
    risk_level: 'low',
    estimated_cost_cents: 800,
    status: 'promoted' as const,
    proposed_by_agent_id: 'agent-bolt',
    approved_by: 'Atlas-01',
    approval_id: null,
    created_at: new Date(Date.now() - 6 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 1 * 86400000).toISOString(),
  },
];

const memoryEntries = [
  {
    id: 'mem-1',
    company_id: COMPANY_ID,
    agent_id: 'agent-bolt',
    scope: 'architecture',
    content: 'All state machines for agent task transitions must enforce strict idempotency and optimistic locking.',
    importance: 0.95,
    tier: 'long_term',
    created_at: new Date(Date.now() - 14 * 86400000).toISOString(),
  },
  {
    id: 'mem-2',
    company_id: COMPANY_ID,
    agent_id: 'agent-sage',
    scope: 'evaluation',
    content: 'A/B prompt evaluations require minimum 50 sample iterations to achieve 95% statistical significance.',
    importance: 0.88,
    tier: 'long_term',
    created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
  },
  {
    id: 'mem-3',
    company_id: COMPANY_ID,
    agent_id: 'agent-shield',
    scope: 'security',
    content: 'All external webhook payloads must be verified against HMAC SHA-256 signatures before queueing.',
    importance: 0.92,
    tier: 'long_term',
    created_at: new Date(Date.now() - 5 * 86400000).toISOString(),
  },
];

const integrations = [
  { id: 'int-gh', name: 'GitHub Enterprise', provider: 'github', connected: true, status: 'healthy', scopes: ['repo', 'workflow', 'read:org'], last_sync: '5 mins ago' },
  { id: 'int-slack', name: 'Slack Ops Channel', provider: 'slack', connected: true, status: 'healthy', scopes: ['chat:write', 'channels:read'], last_sync: '10 mins ago' },
  { id: 'int-m365', name: 'Microsoft Teams / 365', provider: 'm365', connected: false, status: 'disconnected', scopes: [], last_sync: 'never' },
  { id: 'int-azure', name: 'Azure Cloud Vault', provider: 'azure', connected: true, status: 'healthy', scopes: ['KeyVault.Secrets.Read'], last_sync: '1 hour ago' },
];

// ──────────────── API Endpoints ────────────────

app.get('/api/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Pulse Line / Live stream
app.get('/api/v1/companies/:companyId/pulse', (req, res) => {
  res.json(activities);
});

// SSE Stream for Real-time Activity
app.get('/api/v1/companies/:companyId/activity/stream', (req, res) => {
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  const interval = setInterval(() => {
    const randomAgents = ['Atlas-01', 'Nova-02', 'Bolt-03', 'Pixel-04', 'Sage-05', 'Forge-08'];
    const randomActions = ['task.heartbeat', 'cache.hit', 'token.counted', 'route.optimized'];
    const randAgent = randomAgents[Math.floor(Math.random() * randomAgents.length)];
    const randAction = randomActions[Math.floor(Math.random() * randomActions.length)];
    
    const event = {
      id: `act-${Date.now()}`,
      type: randAction,
      actor: randAgent,
      target: 'Core Engine',
      target_id: 'task-4471',
      target_type: 'task',
      timestamp: new Date().toISOString(),
      details: 'Automated telemetry heartbeat',
    };
    res.write(`data: ${JSON.stringify(event)}\n\n`);
  }, 10000);

  req.on('close', () => {
    clearInterval(interval);
    res.end();
  });
});

// Companies
app.get('/api/v1/companies', (req, res) => {
  res.json({ items: companies, total: companies.length, page: 1, page_size: 20, pages: 1 });
});

app.get('/api/v1/companies/:companyId', (req, res) => {
  const company = companies.find((c) => c.id === req.params.companyId) || companies[0];
  res.json(company);
});

// Agents
app.get('/api/v1/companies/:companyId/agents', (req, res) => {
  res.json({ items: agents, total: agents.length, page: 1, page_size: 50, pages: 1 });
});

app.get('/api/v1/companies/:companyId/agents/:agentId', (req, res) => {
  const agent = agents.find((a) => a.id === req.params.agentId);
  if (!agent) return res.status(404).json({ detail: 'Agent not found' });
  res.json(agent);
});

app.post('/api/v1/companies/:companyId/agents', (req, res) => {
  const newAgent = {
    id: `agent-${Date.now().toString(36)}`,
    company_id: req.params.companyId,
    name: req.body.name || 'New-Agent-09',
    title: req.body.title || 'Specialist',
    role: req.body.role || 'engineer',
    department_id: req.body.department_id || 'dept-eng',
    team_id: req.body.team_id || null,
    manager_id: req.body.manager_id || 'agent-nova',
    status: 'active' as const,
    adapter_type: req.body.adapter_type || 'openai',
    model: req.body.model || 'gpt-4o',
    capabilities: req.body.capabilities || ['general_execution'],
    responsibilities: req.body.responsibilities || 'Execute assigned domain tasks',
    objectives: req.body.objectives || 'Maintain high execution velocity',
    budget_monthly_cents: req.body.budget_monthly_cents || 20000,
    spent_monthly_cents: 0,
    performance_score: 90,
    soul_description: req.body.soul_description || '',
    last_heartbeat_at: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  agents.unshift(newAgent);
  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'agent.hired',
    actor: 'Operator',
    target: newAgent.name,
    target_id: newAgent.id,
    target_type: 'agent',
    timestamp: new Date().toISOString(),
    details: `Hired ${newAgent.name} (${newAgent.title})`,
  });
  res.status(201).json(newAgent);
});

app.patch('/api/v1/companies/:companyId/agents/:agentId', (req, res) => {
  const agent = agents.find((a) => a.id === req.params.agentId);
  if (!agent) return res.status(404).json({ detail: 'Agent not found' });
  Object.assign(agent, req.body, { updated_at: new Date().toISOString() });
  res.json(agent);
});

app.delete('/api/v1/companies/:companyId/agents/:agentId', (req, res) => {
  const index = agents.findIndex((a) => a.id === req.params.agentId);
  if (index !== -1) agents.splice(index, 1);
  res.status(204).send();
});

// Bulk agent actions (Pause / Wake)
app.post('/api/v1/companies/:companyId/agents/bulk-status', (req, res) => {
  const { agent_ids, status } = req.body as { agent_ids: string[]; status: 'active' | 'idle' | 'paused' };
  agents.forEach((a) => {
    if (agent_ids?.includes(a.id)) {
      a.status = status;
    }
  });
  res.json({ updated_count: agent_ids?.length || 0, status });
});

// Agent Training / Enhancement
app.post('/api/v1/agents/:agentId/train', (req, res) => {
  const agent = agents.find((a) => a.id === req.params.agentId);
  if (!agent) return res.status(404).json({ detail: 'Agent not found' });
  agent.performance_score = Math.min(100, (agent.performance_score || 90) + 3);
  res.json({ success: true, message: `Training module scheduled for ${agent.name}`, new_score: agent.performance_score });
});

app.post('/api/v1/agents/:agentId/enhance', (req, res) => {
  const agent = agents.find((a) => a.id === req.params.agentId);
  if (!agent) return res.status(404).json({ detail: 'Agent not found' });
  const { capabilities } = req.body;
  if (capabilities && Array.isArray(capabilities)) {
    agent.capabilities = Array.from(new Set([...agent.capabilities, ...capabilities]));
  }
  res.json({ success: true, agent });
});

// Agent Live Chat Conversation
app.get('/api/v1/agents/:agentId/chat', (req, res) => {
  const history = chatHistories[req.params.agentId] || [];
  res.json(history);
});

app.post('/api/v1/agents/:agentId/chat', (req, res) => {
  const agent = agents.find((a) => a.id === req.params.agentId);
  const prompt = req.body.prompt || req.body.message || '';
  if (!chatHistories[req.params.agentId]) {
    chatHistories[req.params.agentId] = [];
  }
  const userMsg = { id: `msg-${Date.now()}`, sender: 'user' as const, text: prompt, timestamp: new Date().toISOString() };
  chatHistories[req.params.agentId].push(userMsg);

  const agentResponse = `${agent?.name || 'Agent'} acknowledges: "${prompt}". Operating parameters within bounds. Telemetry streaming active.`;
  const botMsg = { id: `msg-${Date.now() + 1}`, sender: 'agent' as const, text: agentResponse, timestamp: new Date().toISOString() };
  chatHistories[req.params.agentId].push(botMsg);

  res.json({ message: botMsg, history: chatHistories[req.params.agentId] });
});

// Tasks
app.get('/api/v1/companies/:companyId/tasks', (req, res) => {
  res.json({ items: tasks, total: tasks.length, page: 1, page_size: 50, pages: 1 });
});

app.post('/api/v1/companies/:companyId/tasks', (req, res) => {
  const newTask = {
    id: `task-${Math.floor(1000 + Math.random() * 9000)}`,
    company_id: req.params.companyId,
    project_id: req.body.project_id || 'proj-nexus-v2',
    title: req.body.title || 'Untitled Task',
    description: req.body.description || '',
    status: (req.body.status as 'pending' | 'in_progress' | 'completed' | 'failed') || 'pending',
    priority: req.body.priority ?? 2,
    assigned_agent_id: req.body.assigned_agent_id || 'agent-bolt',
    parent_task_id: req.body.parent_task_id || null,
    result: null,
    error: null,
    started_at: null,
    completed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  tasks.unshift(newTask);
  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'task.created',
    actor: 'Operator',
    target: newTask.title,
    target_id: newTask.id,
    target_type: 'task',
    timestamp: new Date().toISOString(),
    details: `Task #${newTask.id} created`,
  });
  res.status(201).json(newTask);
});

app.patch('/api/v1/companies/:companyId/tasks/:taskId', (req, res) => {
  const task = tasks.find((t) => t.id === req.params.taskId);
  if (!task) return res.status(404).json({ detail: 'Task not found' });
  Object.assign(task, req.body, { updated_at: new Date().toISOString() });
  res.json(task);
});

app.delete('/api/v1/companies/:companyId/tasks/:taskId', (req, res) => {
  const index = tasks.findIndex((t) => t.id === req.params.taskId);
  if (index !== -1) tasks.splice(index, 1);
  res.status(204).send();
});

// Pipelines
app.get('/api/v1/companies/:companyId/pipelines', (req, res) => {
  res.json({ items: pipelines, total: pipelines.length });
});

app.post('/api/v1/companies/:companyId/pipelines', (req, res) => {
  const newPipe = {
    id: `pipe-${Date.now().toString(36)}`,
    name: req.body.name || 'New Pipeline',
    description: req.body.description || '',
    status: 'idle' as const,
    trigger: req.body.trigger || 'manual',
    last_run_at: null,
    success_rate: 100,
    nodes: req.body.nodes || [
      { id: 'node-1', name: 'Start', agent_id: 'agent-nova', status: 'pending' },
    ],
  };
  pipelines.unshift(newPipe);
  res.status(201).json(newPipe);
});

app.post('/api/v1/companies/:companyId/pipelines/:pipeId/trigger', (req, res) => {
  const pipe = pipelines.find((p) => p.id === req.params.pipeId);
  if (!pipe) return res.status(404).json({ detail: 'Pipeline not found' });
  pipe.status = 'running';
  pipe.last_run_at = new Date().toISOString();
  res.json({ message: `Pipeline ${pipe.name} triggered`, pipeline: pipe });
});

// Goals
app.get('/api/v1/companies/:companyId/goals', (req, res) => {
  res.json({ items: goals, total: goals.length });
});

app.post('/api/v1/companies/:companyId/goals', (req, res) => {
  const newGoal = {
    id: `goal-${Date.now().toString(36)}`,
    title: req.body.title || 'New Operational Goal',
    description: req.body.description || '',
    department_id: req.body.department_id || 'dept-eng',
    owner_agent_id: req.body.owner_agent_id || 'agent-nova',
    status: 'in_progress' as const,
    progress: req.body.progress || 0,
    target_date: req.body.target_date || '2026-12-31',
    linked_task_ids: req.body.linked_task_ids || [],
    created_at: new Date().toISOString(),
  };
  goals.unshift(newGoal);
  res.status(201).json(newGoal);
});

app.patch('/api/v1/companies/:companyId/goals/:goalId', (req, res) => {
  const goal = goals.find((g) => g.id === req.params.goalId);
  if (!goal) return res.status(404).json({ detail: 'Goal not found' });
  Object.assign(goal, req.body);
  res.json(goal);
});

// Meetings
app.get('/api/v1/companies/:companyId/meetings', (req, res) => {
  res.json({ items: meetings, total: meetings.length });
});

app.post('/api/v1/companies/:companyId/meetings', (req, res) => {
  const newMeeting = {
    id: `meet-${Date.now().toString(36)}`,
    title: req.body.title || 'Squad Alignment Sync',
    type: req.body.type || 'sync',
    status: 'scheduled',
    scheduled_at: req.body.scheduled_at || new Date(Date.now() + 3600000).toISOString(),
    duration_minutes: req.body.duration_minutes || 30,
    attendees: req.body.attendees || ['agent-atlas', 'agent-nova'],
    transcript: '',
    action_items: [],
  };
  meetings.unshift(newMeeting);
  res.status(201).json(newMeeting);
});

// Organization Chart
app.get('/api/v1/companies/:companyId/organization', (req, res) => {
  res.json({
    company: companies[0],
    departments,
    teams,
    agents,
  });
});

// Organization & Department Endpoints
app.get('/api/v1/companies/:companyId/departments', (req, res) => {
  res.json({ items: departments, total: departments.length });
});

app.post('/api/v1/companies/:companyId/departments', (req, res) => {
  const newDept = {
    id: `dept-${Date.now().toString(36)}`,
    company_id: COMPANY_ID,
    name: req.body.name || 'New Department',
    code: req.body.code || 'DEPT',
    head_agent_id: req.body.head_agent_id || 'agent-atlas',
    head_agent_name: req.body.head_agent_name || 'Atlas-01',
    head_agent_role: req.body.head_agent_role || 'Staff Architect',
    description: req.body.description || '',
    monthly_budget_cents: req.body.monthly_budget_cents || 2500000,
    spent_cents: 0,
    squad_count: 0,
    agent_count: 1,
    color: req.body.color || '#FFB020',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  departments.push(newDept);
  saveOrgConfig();

  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'dept.created',
    actor: 'Operator',
    target: newDept.name,
    target_id: newDept.id,
    target_type: 'dept',
    timestamp: new Date().toISOString(),
    details: `Created organizational department ${newDept.name} (${newDept.code})`,
  });

  res.status(201).json(newDept);
});

app.patch('/api/v1/companies/:companyId/departments/:deptId', (req, res) => {
  const dept = departments.find((d) => d.id === req.params.deptId);
  if (!dept) return res.status(404).json({ detail: 'Department not found' });
  Object.assign(dept, req.body, { updated_at: new Date().toISOString() });
  saveOrgConfig();
  res.json(dept);
});

app.delete('/api/v1/companies/:companyId/departments/:deptId', (req, res) => {
  const index = departments.findIndex((d) => d.id === req.params.deptId);
  if (index !== -1) {
    const deleted = departments.splice(index, 1)[0];
    saveOrgConfig();
    activities.unshift({
      id: `act-${Date.now()}`,
      type: 'dept.deleted',
      actor: 'Operator',
      target: deleted.name,
      target_id: deleted.id,
      target_type: 'dept',
      timestamp: new Date().toISOString(),
      details: `Deleted department ${deleted.name}`,
    });
  }
  res.status(204).send();
});

// Squad Endpoints
app.get('/api/v1/companies/:companyId/squads', (req, res) => {
  res.json({ items: squads, total: squads.length });
});

app.post('/api/v1/companies/:companyId/squads', (req, res) => {
  const newSquad = {
    id: `squad-${Date.now().toString(36)}`,
    department_id: req.body.department_id || 'dept-eng',
    department_name: req.body.department_name || 'Engineering & Core Tech',
    name: req.body.name || 'New Squad Cluster',
    lead_agent_id: req.body.lead_agent_id || 'agent-atlas',
    lead_agent_name: req.body.lead_agent_name || 'Atlas-01',
    lead_role: req.body.lead_role || 'Squad Lead',
    description: req.body.description || '',
    agent_ids: req.body.agent_ids || ['agent-atlas'],
    color: req.body.color || '#FFB020',
    active_tasks_count: req.body.active_tasks_count || 3,
    ast_coverage: req.body.ast_coverage || 98,
    health_status: req.body.health_status || 'healthy',
    created_at: new Date().toISOString(),
  };

  squads.unshift(newSquad);
  saveOrgConfig();

  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'squad.created',
    actor: 'Operator',
    target: newSquad.name,
    target_id: newSquad.id,
    target_type: 'squad',
    timestamp: new Date().toISOString(),
    details: `Created squad cluster ${newSquad.name}`,
  });

  res.status(201).json(newSquad);
});

app.patch('/api/v1/companies/:companyId/squads/:squadId', (req, res) => {
  const squad = squads.find((s) => s.id === req.params.squadId);
  if (!squad) return res.status(404).json({ detail: 'Squad not found' });
  Object.assign(squad, req.body);
  saveOrgConfig();
  res.json(squad);
});

// Skills API Endpoints
app.get('/api/v1/companies/:companyId/skills', (req, res) => {
  res.json({ items: skills, total: skills.length });
});

app.get('/api/v1/companies/:companyId/skills/:skillId', (req, res) => {
  const skill = skills.find((s) => s.id === req.params.skillId);
  if (!skill) return res.status(404).json({ detail: 'Skill not found' });
  res.json(skill);
});

app.post('/api/v1/companies/:companyId/skills', (req, res) => {
  const newSkill = {
    id: `skill-${Date.now().toString(36)}`,
    name: req.body.name || 'New Custom Skill',
    category: req.body.category || 'Engineering',
    description: req.body.description || 'Custom capability registered in Mission Control',
    source_type: req.body.source_type || 'custom',
    source_location: req.body.source_location || 'Code Editor',
    version: req.body.version || '1.0.0',
    author: req.body.author || 'Operator',
    enabled: req.body.enabled ?? true,
    security_status: req.body.security_status || 'verified',
    call_count_30d: 0,
    success_rate: '100%',
    avg_execution_ms: Math.floor(40 + Math.random() * 200),
    equipped_agents: req.body.equipped_agents || ['Atlas-01'],
    instructions_md: req.body.instructions_md || '# Skill Instructions\n\n- Standard skill execution rules',
    parameters_json: req.body.parameters_json || '{\n  "type": "object"\n}',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };

  skills.unshift(newSkill);
  saveSkillsConfig();

  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'skill.registered',
    actor: 'Operator',
    target: newSkill.name,
    target_id: newSkill.id,
    target_type: 'skill',
    timestamp: new Date().toISOString(),
    details: `Registered new workforce skill ${newSkill.name} (${newSkill.source_type.toUpperCase()})`,
  });

  res.status(201).json(newSkill);
});

app.patch('/api/v1/companies/:companyId/skills/:skillId', (req, res) => {
  const skill = skills.find((s) => s.id === req.params.skillId);
  if (!skill) return res.status(404).json({ detail: 'Skill not found' });
  Object.assign(skill, req.body, { updated_at: new Date().toISOString() });
  saveSkillsConfig();
  res.json(skill);
});

app.delete('/api/v1/companies/:companyId/skills/:skillId', (req, res) => {
  const index = skills.findIndex((s) => s.id === req.params.skillId);
  if (index !== -1) {
    const deleted = skills.splice(index, 1)[0];
    saveSkillsConfig();
    activities.unshift({
      id: `act-${Date.now()}`,
      type: 'skill.uninstalled',
      actor: 'Operator',
      target: deleted.name,
      target_id: deleted.id,
      target_type: 'skill',
      timestamp: new Date().toISOString(),
      details: `Uninstalled skill package ${deleted.name}`,
    });
  }
  res.status(204).send();
});

// Test Sandbox Execution Endpoint
app.post('/api/v1/companies/:companyId/skills/:skillId/test', (req, res) => {
  const skill = skills.find((s) => s.id === req.params.skillId);
  if (!skill) return res.status(404).json({ detail: 'Skill not found' });

  const executionTime = Math.floor(45 + Math.random() * 120);
  const sampleOutput = `[Skill Sandbox Runner]\n✔ Successfully validated tool binding for '${skill.name}'\n✔ Parsed input parameter schema\n✔ Output payload: {\n  "status": "success",\n  "verified_at": "${new Date().toISOString()}",\n  "result": "Skill execution envelope evaluated clean across sandboxed runtime."\n}`;

  res.json({
    success: true,
    output: sampleOutput,
    execution_ms: executionTime,
    tokens_used: Math.floor(80 + Math.random() * 150),
  });
});

// Tools
app.get('/api/v1/companies/:companyId/tools', (req, res) => {
  res.json({ items: tools, total: tools.length });
});

app.post('/api/v1/companies/:companyId/tools', (req, res) => {
  const newTool = {
    id: `tool-${Date.now().toString(36)}`,
    name: req.body.name,
    category: req.body.category || 'Utility',
    status: 'available',
    call_count_30d: 0,
    error_rate: '0.00%',
    allowed_roles: req.body.allowed_roles || ['engineer', 'devops'],
  };
  tools.unshift(newTool);
  res.status(201).json(newTool);
});

// Helper function to fetch real GitHub repository branches, commits, PRs, and contributors
async function fetchGitHubRepoDetails(fullName: string, token: string | null) {
  let language = 'TypeScript';
  let stars = 0;
  let description = `Real GitHub repository (${fullName})`;
  let defaultBranch = 'main';
  let branches: any[] = [];
  let commits: any[] = [];
  let prs: any[] = [];
  let contributors: any[] = [];

  if (!token) {
    return { language, stars, description, defaultBranch, branches, commits, prs, contributors };
  }

  const headers = {
    Authorization: `Bearer ${token}`,
    'User-Agent': 'Nexus-Mission-Control',
    Accept: 'application/vnd.github.v3+json',
  };

  try {
    // 1. Fetch main repo details
    const repoRes = await fetch(`https://api.github.com/repos/${fullName}`, { headers });
    if (repoRes.ok) {
      const r = await repoRes.json();
      language = r.language || 'TypeScript';
      stars = r.stargazers_count || 0;
      description = r.description || description;
      defaultBranch = r.default_branch || 'main';
    }

    // 2. Fetch ALL real branches
    const branchesRes = await fetch(`https://api.github.com/repos/${fullName}/branches?per_page=100`, { headers });
    if (branchesRes.ok) {
      const branchesData = await branchesRes.json();
      branches = branchesData.map((b: any) => ({
        name: b.name,
        is_protected: b.protected || b.name === defaultBranch,
        last_commit_hash: b.commit?.sha?.substring(0, 7) || 'HEAD',
        last_commit_message: `Commit on branch ${b.name}`,
        last_commit_time: 'Recently',
      }));
    }

    // 3. Fetch real commits timeline (up to 30)
    const commitsRes = await fetch(`https://api.github.com/repos/${fullName}/commits?per_page=30`, { headers });
    if (commitsRes.ok) {
      const commitsData = await commitsRes.json();
      commits = commitsData.map((c: any) => ({
        hash: c.sha?.substring(0, 7) || 'c000000',
        full_hash: c.sha,
        message: c.commit?.message || 'Remote GitHub commit',
        author: c.commit?.author?.name || c.author?.login || 'GitHub Contributor',
        author_avatar: c.author?.avatar_url,
        relative_time: 'Recently',
        timestamp: c.commit?.author?.date || new Date().toISOString(),
        additions: Math.floor(12 + Math.random() * 80),
        deletions: Math.floor(2 + Math.random() * 20),
        ast_indexed: true,
        html_url: c.html_url,
      }));
    }

    // 4. Fetch real Pull Requests (open, closed, merged)
    const prsRes = await fetch(`https://api.github.com/repos/${fullName}/pulls?state=all&per_page=30`, { headers });
    if (prsRes.ok) {
      const prsData = await prsRes.json();
      prs = prsData.map((p: any) => {
        let status: 'open' | 'closed' | 'merged' = 'open';
        if (p.state === 'closed') {
          status = p.merged_at ? 'merged' : 'closed';
        }
        return {
          id: `pr-gh-${p.number}`,
          number: p.number,
          title: p.title,
          description: p.body || 'Live GitHub Pull Request',
          author: p.user?.login || 'GitHub User',
          author_role: 'GitHub Contributor',
          status,
          checks: 'passed' as const,
          source_branch: p.head?.ref || 'feature',
          target_branch: p.base?.ref || 'main',
          additions: p.additions || 25,
          deletions: p.deletions || 5,
          changed_files_count: 2,
          created_at: p.created_at,
          updated_at: p.updated_at,
          ai_review_score: 98,
          html_url: p.html_url,
          ai_summary: 'Remote GitHub PR synchronized from GitHub REST API.',
          reviewers: [],
          diff_preview: `diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1,3 +1,5 @@\n+# ${p.title}\n+See full live diff on GitHub: ${p.html_url}`,
        };
      });
    }

    // 5. Fetch real contributors
    const contribRes = await fetch(`https://api.github.com/repos/${fullName}/contributors?per_page=30`, { headers });
    if (contribRes.ok) {
      const contribData = await contribRes.json();
      if (Array.isArray(contribData)) {
        contributors = contribData.map((c: any) => ({
          name: c.login,
          role: 'Contributor',
          commits: c.contributions || 1,
          avatar_url: c.avatar_url,
        }));
      }
    }
  } catch (err) {
    // Ignore network errors
  }

  if (branches.length === 0) {
    branches = [{ name: defaultBranch, is_protected: true, last_commit_hash: 'head', last_commit_message: 'Default branch HEAD', last_commit_time: 'Recently' }];
  }

  return { language, stars, description, defaultBranch, branches, commits, prs, contributors };
}

// Repositories & Agent PRs (Returns ONLY manually imported repositories)
const handleGetRepos = (req: express.Request, res: express.Response) => {
  res.json({ items: repos, total: repos.length });
};

app.get('/api/v1/companies/:companyId/repos', handleGetRepos);
app.get('/api/v1/companies/:companyId/git-repos', handleGetRepos);

const handleGetRepoById = (req: express.Request, res: express.Response) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repository not found' });
  res.json(repo);
};

app.get('/api/v1/companies/:companyId/repos/:repoId', handleGetRepoById);
app.get('/api/v1/companies/:companyId/git-repos/:repoId', handleGetRepoById);

const handleCreateRepo = (req: express.Request, res: express.Response) => {
  const name = req.body.name || 'org/new-repo';
  const newRepo = {
    id: `repo-${Date.now().toString(36)}`,
    name,
    description: req.body.description || 'Connected source codebase for autonomous agent development',
    provider: req.body.provider || 'github',
    visibility: req.body.visibility || 'private',
    default_branch: req.body.default_branch || 'main',
    language: req.body.language || 'TypeScript',
    stars_or_watchers: 1,
    sync_status: 'synced' as const,
    last_sync_at: new Date().toISOString(),
    ast_index_coverage: 95,
    security_score: 100,
    open_prs_count: 0,
    total_commits_7d: 1,
    lines_of_code: req.body.lines_of_code || 12400,
    assigned_agents: req.body.assigned_agents || ['Nova-02', 'Atlas-01'],
    auto_review_enabled: req.body.auto_review_enabled ?? true,
    webhook_url: `https://api.nexus.nvlabs.internal/webhooks/${name.replace(/[^a-zA-Z0-9]/g, '-').toLowerCase()}`,
    branches: [
      { name: req.body.default_branch || 'main', is_protected: true, last_commit_hash: 'c104e12', last_commit_message: 'Initial repo mount and AST index bootstrap', last_commit_time: 'Just now' },
    ],
    commits: [
      { hash: 'c104e12', message: 'Initial repo mount and AST index bootstrap', author: 'Atlas-01', relative_time: 'Just now', timestamp: new Date().toISOString(), additions: 50, deletions: 0, ast_indexed: true },
    ],
    prs: [],
    contributors: [
      { name: 'Atlas-01', role: 'Chief Executive Officer', commits: 1 },
    ],
  };
  repos.unshift(newRepo);
  saveImportedRepos();
  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'repo.synced',
    actor: 'Operator',
    target: newRepo.name,
    target_id: newRepo.id,
    target_type: 'repo',
    timestamp: new Date().toISOString(),
    details: `Mounted repository ${newRepo.name}`,
  });
  res.status(201).json(newRepo);
};

app.post('/api/v1/companies/:companyId/repos', handleCreateRepo);
app.post('/api/v1/companies/:companyId/git-repos', handleCreateRepo);

// Update Repo configuration
app.patch('/api/v1/companies/:companyId/repos/:repoId', (req, res) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repository not found' });
  Object.assign(repo, req.body);
  saveImportedRepos();
  res.json(repo);
});

// Delete / Unmount Repo
app.delete('/api/v1/companies/:companyId/repos/:repoId', (req, res) => {
  const index = repos.findIndex((r) => r.id === req.params.repoId);
  if (index !== -1) {
    const deleted = repos.splice(index, 1)[0];
    saveImportedRepos();
    activities.unshift({
      id: `act-${Date.now()}`,
      type: 'repo.unmounted',
      actor: 'Operator',
      target: deleted.name,
      target_id: deleted.id,
      target_type: 'repo',
      timestamp: new Date().toISOString(),
      details: `Unmounted repository ${deleted.name}`,
    });
  }
  res.status(204).send();
});

// --- REAL GITHUB CONNECTOR API ENDPOINTS ---

// GitHub Connect / Verify Token Endpoint
app.post('/api/v1/companies/:companyId/github/connect', async (req, res) => {
  const token = req.body.token || req.body.github_token || githubState.token;
  if (!token) {
    return res.status(400).json({ detail: 'GitHub Personal Access Token is required' });
  }

  try {
    const ghRes = await fetch('https://api.github.com/user', {
      headers: {
        Authorization: `Bearer ${token}`,
        'User-Agent': 'Nexus-Mission-Control',
        Accept: 'application/vnd.github.v3+json',
      },
    });

    if (!ghRes.ok) {
      const errJson = await ghRes.json().catch(() => ({}));
      return res.status(ghRes.status).json({
        authenticated: false,
        detail: errJson.message || 'Invalid GitHub token or authentication failed',
      });
    }

    const userData = await ghRes.json();
    githubState.token = token;
    githubState.authenticated = true;
    githubState.user = userData;
    githubState.lastCheckedAt = new Date().toISOString();

    // Save token persistently to disk database
    saveGitHubConfig(token, userData);

    activities.unshift({
      id: `act-${Date.now()}`,
      type: 'github.connected',
      actor: 'Operator',
      target: `@${userData.login}`,
      target_id: userData.id?.toString() || 'gh-user',
      target_type: 'github',
      timestamp: new Date().toISOString(),
      details: `Connected GitHub account @${userData.login} (${userData.public_repos || 0} public repos)`,
    });

    res.json({
      authenticated: true,
      user: {
        login: userData.login,
        name: userData.name || userData.login,
        avatar_url: userData.avatar_url,
        html_url: userData.html_url,
        public_repos: userData.public_repos,
        followers: userData.followers,
      },
      message: `Successfully connected to GitHub as @${userData.login}`,
    });
  } catch (err: any) {
    res.status(500).json({ authenticated: false, detail: err.message || 'Network error connecting to GitHub API' });
  }
});

// GitHub Connection Status Endpoint
app.get('/api/v1/companies/:companyId/github/status', (req, res) => {
  res.json({
    authenticated: githubState.authenticated,
    user: githubState.user ? {
      login: githubState.user.login,
      name: githubState.user.name || githubState.user.login,
      avatar_url: githubState.user.avatar_url,
      html_url: githubState.user.html_url,
      public_repos: githubState.user.public_repos,
    } : null,
    hasToken: !!githubState.token,
    lastCheckedAt: githubState.lastCheckedAt,
  });
});

// Fetch Live Remote GitHub Repositories
app.get('/api/v1/companies/:companyId/github/user-repos', async (req, res) => {
  const token = githubState.token || (req.headers.authorization ? req.headers.authorization.replace('Bearer ', '') : null);
  if (!token) {
    return res.status(401).json({ detail: 'GitHub token not connected. Please connect your GitHub PAT first.' });
  }

  try {
    const ghRes = await fetch('https://api.github.com/user/repos?sort=updated&per_page=30', {
      headers: {
        Authorization: `Bearer ${token}`,
        'User-Agent': 'Nexus-Mission-Control',
        Accept: 'application/vnd.github.v3+json',
      },
    });

    if (!ghRes.ok) {
      return res.status(ghRes.status).json({ detail: 'Failed to fetch repositories from GitHub API' });
    }

    const ghRepos = await ghRes.json();
    const items = ghRepos.map((r: any) => ({
      id: `gh-${r.id}`,
      name: r.full_name,
      description: r.description || 'GitHub repository',
      provider: 'github',
      visibility: r.private ? 'private' : 'public',
      default_branch: r.default_branch || 'main',
      language: r.language || 'TypeScript',
      stars: r.stargazers_count || 0,
      forks: r.forks_count || 0,
      html_url: r.html_url,
      clone_url: r.clone_url,
      updated_at: r.updated_at,
    }));

    res.json({ items, total: items.length });
  } catch (err: any) {
    res.status(500).json({ detail: err.message || 'Error communicating with GitHub API' });
  }
});



// Trigger Repository Sync & AST Re-indexing
app.post('/api/v1/companies/:companyId/repos/:repoId/sync', async (req, res) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repo not found' });

  // If repo is a real GitHub repo, refresh details live from GitHub API!
  if (repo.name && repo.name.includes('/') && githubState.token) {
    const details = await fetchGitHubRepoDetails(repo.name, githubState.token);
    repo.branches = details.branches;
    repo.commits = details.commits;
    repo.prs = details.prs;
    repo.contributors = details.contributors;
    repo.open_prs_count = details.prs.filter((p: any) => p.status === 'open').length;
    repo.language = details.language;
    repo.stars_or_watchers = details.stars;
  }

  repo.last_sync_at = new Date().toISOString();
  repo.sync_status = 'synced';
  repo.ast_index_coverage = 100;
  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'repo.synced',
    actor: 'Forge-08',
    target: repo.name,
    target_id: repo.id,
    target_type: 'repo',
    timestamp: new Date().toISOString(),
    details: `Synchronized repository ${repo.name} with live GitHub branches and commits`,
  });
  res.json({ message: `Repository ${repo.name} synchronized successfully with live GitHub data`, repo });
});

// Import Remote GitHub Repo into System
app.post('/api/v1/companies/:companyId/github/import', async (req, res) => {
  const { full_name, default_branch } = req.body;
  if (!full_name) {
    return res.status(400).json({ detail: 'Repository full_name (e.g. owner/repo) is required' });
  }

  const token = githubState.token;
  const details = await fetchGitHubRepoDetails(full_name, token);

  const newRepo = {
    id: `repo-gh-${Date.now().toString(36)}`,
    name: full_name,
    description: details.description || `Real GitHub connected repository (${full_name})`,
    provider: 'github' as const,
    visibility: 'public' as const,
    default_branch: default_branch || details.defaultBranch || 'main',
    language: details.language,
    stars_or_watchers: details.stars || 1,
    sync_status: 'synced' as const,
    last_sync_at: new Date().toISOString(),
    ast_index_coverage: 100,
    security_score: 98,
    open_prs_count: details.prs.filter((p: any) => p.status === 'open').length,
    total_commits_7d: details.commits.length || 5,
    lines_of_code: 15400,
    assigned_agents: ['Atlas-01', 'Nova-02', 'Bolt-03'],
    auto_review_enabled: true,
    webhook_url: `https://api.github.com/repos/${full_name}/events`,
    branches: details.branches,
    commits: details.commits,
    prs: details.prs,
    contributors: details.contributors.length ? details.contributors : [
      { name: githubState.user?.login || 'Maintainer', role: 'Maintainer', commits: 5 },
    ],
  };

  repos.unshift(newRepo);
  saveImportedRepos();
  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'github.imported',
    actor: 'Operator',
    target: full_name,
    target_id: newRepo.id,
    target_type: 'repo',
    timestamp: new Date().toISOString(),
    details: `Imported live GitHub repository ${full_name} (${details.branches.length} branches, ${details.commits.length} commits)`,
  });

  res.status(201).json(newRepo);
});

// Create REAL Branch on GitHub
app.post('/api/v1/companies/:companyId/github/repos/:owner/:repo/branches', async (req, res) => {
  const { owner, repo } = req.params;
  const { branch_name, from_branch } = req.body;
  const token = githubState.token;

  if (!token) {
    return res.status(401).json({ detail: 'GitHub token required to create branch on GitHub' });
  }

  try {
    // 1. Get base branch SHA
    const baseBranch = from_branch || 'main';
    const refRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/git/ref/heads/${baseBranch}`, {
      headers: { Authorization: `Bearer ${token}`, 'User-Agent': 'Nexus-Mission-Control' },
    });
    if (!refRes.ok) {
      return res.status(400).json({ detail: `Base branch '${baseBranch}' not found on GitHub` });
    }
    const refData = await refRes.json();
    const sha = refData.object?.sha;

    // 2. Create new branch reference
    const createRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/git/refs`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'User-Agent': 'Nexus-Mission-Control',
        'Content-Type': 'application/json',
        Accept: 'application/vnd.github.v3+json',
      },
      body: JSON.stringify({
        ref: `refs/heads/${branch_name}`,
        sha,
      }),
    });
    const createData = await createRes.json();
    if (!createRes.ok) {
      return res.status(createRes.status).json({ detail: createData.message || 'GitHub branch creation failed' });
    }

    // Update local repo object if present
    const localRepo = repos.find((r) => r.name === `${owner}/${repo}`);
    const newBranchObj = {
      name: branch_name,
      is_protected: false,
      last_commit_hash: sha?.substring(0, 7) || 'HEAD',
      last_commit_message: `Created branch ${branch_name}`,
      last_commit_time: 'Just now',
    };
    if (localRepo) {
      localRepo.branches.push(newBranchObj);
    }

    res.status(201).json({
      success: true,
      branch: newBranchObj,
      message: `Branch '${branch_name}' created on GitHub successfully!`,
    });
  } catch (err: any) {
    res.status(500).json({ detail: err.message || 'Error calling GitHub API' });
  }
});

// Create REAL Pull Request on GitHub
app.post('/api/v1/companies/:companyId/github/repos/:owner/:repo/pulls', async (req, res) => {
  const { owner, repo } = req.params;
  const { title, body, head, base } = req.body;
  const token = githubState.token;

  if (!token) {
    return res.status(401).json({ detail: 'GitHub token required to submit live PR to GitHub' });
  }

  try {
    const ghRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/pulls`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'User-Agent': 'Nexus-Mission-Control',
        'Content-Type': 'application/json',
        Accept: 'application/vnd.github.v3+json',
      },
      body: JSON.stringify({
        title: title || 'Automated Agent PR',
        body: body || 'Submitted via NEXUS Autonomous Mission Control',
        head: head || 'agent/patch',
        base: base || 'main',
      }),
    });

    const ghData = await ghRes.json();
    if (!ghRes.ok) {
      return res.status(ghRes.status).json({ detail: ghData.message || 'GitHub PR creation failed', errors: ghData.errors });
    }

    res.status(201).json({
      success: true,
      pr: {
        id: `pr-gh-${ghData.number}`,
        number: ghData.number,
        title: ghData.title,
        html_url: ghData.html_url,
        state: ghData.state,
        head: ghData.head?.ref,
        base: ghData.base?.ref,
      },
      message: `Live GitHub Pull Request #${ghData.number} created successfully!`,
    });
  } catch (err: any) {
    res.status(500).json({ detail: err.message || 'Error calling GitHub API' });
  }
});

// Create REAL Commit / File Edit on GitHub
app.post('/api/v1/companies/:companyId/github/repos/:owner/:repo/contents', async (req, res) => {
  const { owner, repo } = req.params;
  const { path, message, content, branch, sha } = req.body;
  const token = githubState.token;

  if (!token) {
    return res.status(401).json({ detail: 'GitHub token required to push live commit to GitHub' });
  }

  try {
    const contentBase64 = Buffer.from(content || '// Autonomous Agent Commit').toString('base64');
    const payload: any = {
      message: message || 'feat: autonomous agent commit update',
      content: contentBase64,
      branch: branch || 'main',
    };
    if (sha) payload.sha = sha;

    const ghRes = await fetch(`https://api.github.com/repos/${owner}/${repo}/contents/${path || 'NEXUS.md'}`, {
      method: 'PUT',
      headers: {
        Authorization: `Bearer ${token}`,
        'User-Agent': 'Nexus-Mission-Control',
        'Content-Type': 'application/json',
        Accept: 'application/vnd.github.v3+json',
      },
      body: JSON.stringify(payload),
    });

    const ghData = await ghRes.json();
    if (!ghRes.ok) {
      return res.status(ghRes.status).json({ detail: ghData.message || 'GitHub commit creation failed' });
    }

    res.status(201).json({
      success: true,
      commit: {
        sha: ghData.commit?.sha,
        html_url: ghData.commit?.html_url,
        message: ghData.commit?.message,
      },
      message: `Live GitHub Commit pushed successfully to ${branch || 'main'} branch!`,
    });
  } catch (err: any) {
    res.status(500).json({ detail: err.message || 'Error calling GitHub API' });
  }
});

app.post('/api/v1/companies/:companyId/repos/:repoId/prs', (req, res) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repository not found' });
  
  const prNumber = (repo.prs.length ? Math.max(...repo.prs.map((p) => p.number)) : 100) + 1;
  const authorAgent = req.body.author || 'Bolt-03';
  const sourceBranch = req.body.source_branch || `agent/${authorAgent.toLowerCase().replace(/[^a-z0-9]/g, '-')}/patch-${Date.now().toString(36)}`;
  
  const newPR = {
    id: `pr-${prNumber}`,
    number: prNumber,
    title: req.body.title || 'Automated agent refactoring & performance optimization',
    description: req.body.description || 'Agent generated patch with AST validation and isolated unit tests.',
    author: authorAgent,
    author_role: req.body.author_role || 'Agent Engineer',
    status: 'open' as const,
    checks: 'passed' as const,
    source_branch: sourceBranch,
    target_branch: req.body.target_branch || repo.default_branch,
    additions: req.body.additions || Math.floor(40 + Math.random() * 200),
    deletions: req.body.deletions || Math.floor(5 + Math.random() * 40),
    changed_files_count: req.body.changed_files_count || Math.floor(1 + Math.random() * 5),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    ai_review_score: 98,
    ai_summary: 'Automated static analysis passed with zero regressions. All AST symbols resolved cleanly.',
    reviewers: [
      {
        agent_name: 'Nova-02',
        decision: 'approved' as const,
        comment: 'Automated architectural verification passed. Code conforms to squad style guidelines.',
        timestamp: 'Just now',
      },
    ],
    diff_preview: req.body.diff_preview || `diff --git a/src/index.ts b/src/index.ts\n--- a/src/index.ts\n+++ b/src/index.ts\n@@ -1,5 +1,8 @@\n-// Agent optimized routines\n+export function runOptimizedRoutine() {\n+  return { status: 'accelerated', verified: true };\n+}`,
  };

  repo.prs.unshift(newPR);
  repo.open_prs_count = repo.prs.filter((p) => p.status === 'open').length;

  // Add branch if not exists
  if (!repo.branches.some((b) => b.name === sourceBranch)) {
    repo.branches.push({
      name: sourceBranch,
      is_protected: false,
      last_commit_hash: `p${Date.now().toString(16).slice(-6)}`,
      last_commit_message: newPR.title,
      last_commit_time: 'Just now',
    });
  }

  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'task.completed',
    actor: authorAgent,
    target: `PR #${prNumber} on ${repo.name}`,
    target_id: repo.id,
    target_type: 'repo',
    timestamp: new Date().toISOString(),
    details: `Drafted pull request #${prNumber}: "${newPR.title}"`,
  });

  res.status(201).json(newPR);
});

// Trigger Automated Agent Review on PR
app.post('/api/v1/companies/:companyId/repos/:repoId/prs/:prId/review', (req, res) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repository not found' });
  const pr = repo.prs.find((p) => p.id === req.params.prId || String(p.number) === req.params.prId);
  if (!pr) return res.status(404).json({ detail: 'Pull Request not found' });

  const reviewer = req.body.reviewer || 'Shield-07';
  const newReview = {
    agent_name: reviewer,
    decision: 'approved' as const,
    comment: req.body.comment || `AST security & performance audit verified. Zero CVE vulnerabilities detected. Fuzz test score 100%.`,
    timestamp: 'Just now',
  };
  pr.reviewers.unshift(newReview);
  pr.ai_review_score = 99;
  pr.updated_at = new Date().toISOString();

  res.json({ message: `Agent ${reviewer} completed automated code review on PR #${pr.number}`, pr });
});

// Merge Pull Request
app.post('/api/v1/companies/:companyId/repos/:repoId/prs/:prId/merge', (req, res) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repository not found' });
  const pr = repo.prs.find((p) => p.id === req.params.prId || String(p.number) === req.params.prId);
  if (!pr) return res.status(404).json({ detail: 'Pull Request not found' });

  pr.status = 'merged';
  pr.updated_at = new Date().toISOString();
  repo.open_prs_count = repo.prs.filter((p) => p.status === 'open').length;

  const commitHash = `m${Date.now().toString(16).slice(-6)}`;
  repo.commits.unshift({
    hash: commitHash,
    message: `Merge pull request #${pr.number} from ${pr.source_branch}: ${pr.title}`,
    author: pr.author,
    relative_time: 'Just now',
    timestamp: new Date().toISOString(),
    additions: pr.additions,
    deletions: pr.deletions,
    ast_indexed: true,
  });

  activities.unshift({
    id: `act-${Date.now()}`,
    type: 'repo.synced',
    actor: 'Nova-02',
    target: `Merged PR #${pr.number} into ${repo.name}`,
    target_id: repo.id,
    target_type: 'repo',
    timestamp: new Date().toISOString(),
    details: `Merged PR #${pr.number}: ${pr.title}`,
  });

  res.json({ message: `PR #${pr.number} successfully merged into ${repo.default_branch}`, pr, repo });
});

// Close Pull Request
app.post('/api/v1/companies/:companyId/repos/:repoId/prs/:prId/close', (req, res) => {
  const repo = repos.find((r) => r.id === req.params.repoId);
  if (!repo) return res.status(404).json({ detail: 'Repository not found' });
  const pr = repo.prs.find((p) => p.id === req.params.prId || String(p.number) === req.params.prId);
  if (!pr) return res.status(404).json({ detail: 'Pull Request not found' });

  pr.status = 'closed';
  pr.updated_at = new Date().toISOString();
  repo.open_prs_count = repo.prs.filter((p) => p.status === 'open').length;
  res.json({ message: `PR #${pr.number} closed`, pr });
});

// Aggregated All PRs across all repositories
app.get('/api/v1/companies/:companyId/prs', (req, res) => {
  const allPRs: any[] = [];
  repos.forEach((repo) => {
    (repo.prs || []).forEach((pr) => {
      allPRs.push({
        ...pr,
        repo_id: repo.id,
        repo_name: repo.name,
        repo_language: repo.language,
        repo_default_branch: repo.default_branch,
      });
    });
  });
  // Sort recently updated or created
  allPRs.sort((a, b) => new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime());
  res.json({ items: allPRs, total: allPRs.length });
});

// Aggregated All Commits across all repositories
app.get('/api/v1/companies/:companyId/commits', (req, res) => {
  const allCommits: any[] = [];
  repos.forEach((repo) => {
    (repo.commits || []).forEach((commit) => {
      allCommits.push({
        ...commit,
        repo_id: repo.id,
        repo_name: repo.name,
        repo_language: repo.language,
        repo_default_branch: repo.default_branch,
      });
    });
  });
  // Sort by timestamp descending
  allCommits.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
  res.json({ items: allCommits, total: allCommits.length });
});

// Knowledge Base
app.get('/api/v1/companies/:companyId/knowledge', (req, res) => {
  res.json({ items: knowledgeArticles, total: knowledgeArticles.length });
});

app.post('/api/v1/companies/:companyId/knowledge', (req, res) => {
  const newDoc = {
    id: `kb-${Date.now().toString(36)}`,
    title: req.body.title,
    category: req.body.category || 'General',
    author: req.body.author || 'Operator',
    excerpt: (req.body.content || '').substring(0, 120),
    content: req.body.content || '',
    tags: req.body.tags || [],
    views: 1,
    updated_at: new Date().toISOString(),
  };
  knowledgeArticles.unshift(newDoc);
  res.status(201).json(newDoc);
});

// Notifications
app.get('/api/v1/companies/:companyId/notifications', (req, res) => {
  res.json({ items: notifications, total: notifications.length });
});

app.patch('/api/v1/companies/:companyId/notifications/:notifId', (req, res) => {
  const notif = notifications.find((n) => n.id === req.params.notifId);
  if (notif) {
    Object.assign(notif, req.body);
  }
  res.json(notif);
});

app.get('/api/v1/notifications/preferences', (req, res) => {
  res.json(notifPreferences);
});

app.put('/api/v1/notifications/preferences', (req, res) => {
  notifPreferences = { ...notifPreferences, ...req.body };
  res.json({ success: true, preferences: notifPreferences });
});

// Activity
app.get('/api/v1/companies/:companyId/activity', (req, res) => {
  res.json({ items: activities, total: activities.length });
});

// Budgets
app.get('/api/v1/companies/:companyId/budget-policies', (req, res) => {
  res.json({ items: budgetPolicies, total: budgetPolicies.length });
});

app.post('/api/v1/companies/:companyId/budget-policies', (req, res) => {
  const newPolicy = {
    id: `policy-${Date.now().toString(36)}`,
    company_id: COMPANY_ID,
    scope_type: req.body.scope_type || 'department',
    scope_id: req.body.scope_id || 'dept-eng',
    metric: 'cost' as const,
    window_kind: 'monthly' as const,
    amount: req.body.amount || 200000,
    warn_percent: req.body.warn_percent || 80,
    hard_stop_enabled: req.body.hard_stop_enabled ?? true,
    is_active: true,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  budgetPolicies.unshift(newPolicy);
  res.status(201).json(newPolicy);
});

app.get('/api/v1/companies/:companyId/budget-usage', (req, res) => {
  res.json([
    { scope_type: 'company', scope_id: COMPANY_ID, total_cost_cents: 423500, total_input_tokens: 8450000, total_output_tokens: 3120000, event_count: 1420 },
    { scope_type: 'department', scope_id: 'dept-eng', total_cost_cents: 210000, total_input_tokens: 4320000, total_output_tokens: 1650000, event_count: 780 },
    { scope_type: 'department', scope_id: 'dept-ai', total_cost_cents: 78500, total_input_tokens: 2100000, total_output_tokens: 820000, event_count: 320 },
  ]);
});

// Evolution
app.get('/api/v1/companies/:companyId/evolution/proposals', (req, res) => {
  res.json({ items: proposals, total: proposals.length });
});

app.post('/api/v1/companies/:companyId/evolution/proposals', (req, res) => {
  const newProp = {
    id: `prop-${Math.floor(100 + Math.random() * 900)}`,
    company_id: COMPANY_ID,
    proposal_type: req.body.proposal_type || 'prompt_optimization',
    title: req.body.title || 'Optimization Proposal',
    description: req.body.description || '',
    expected_impact: req.body.expected_impact || '+15% efficiency',
    confidence: 0.91,
    risk_level: 'low',
    estimated_cost_cents: 500,
    status: 'evaluating' as const,
    proposed_by_agent_id: req.body.proposed_by_agent_id || 'agent-sage',
    approved_by: null,
    approval_id: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  proposals.unshift(newProp);
  res.status(201).json(newProp);
});

app.post('/api/v1/companies/:companyId/evolution/proposals/:propId/decide', (req, res) => {
  const prop = proposals.find((p) => p.id === req.params.propId);
  if (!prop) return res.status(404).json({ detail: 'Proposal not found' });
  const { decision, reason } = req.body;
  prop.status = decision === 'approve' ? 'promoted' : 'rejected';
  prop.approved_by = decision === 'approve' ? 'Operator' : null;
  res.json({ success: true, proposal: prop, reason });
});

// Memory
app.get('/api/v1/companies/:companyId/memory', (req, res) => {
  res.json({ items: memoryEntries, total: memoryEntries.length });
});

app.get('/api/v1/agents/:agentId/memory', (req, res) => {
  const agentMemories = memoryEntries.filter((m) => m.agent_id === req.params.agentId);
  res.json({ items: agentMemories.length ? agentMemories : memoryEntries, total: agentMemories.length || memoryEntries.length });
});

// Settings & Integrations
app.get('/api/v1/settings/integrations', (req, res) => {
  res.json(integrations);
});

app.post('/api/v1/settings/integrations/:intId/toggle', (req, res) => {
  const item = integrations.find((i) => i.id === req.params.intId);
  if (item) {
    item.connected = !item.connected;
    item.status = item.connected ? 'healthy' : 'disconnected';
  }
  res.json(item);
});

// Workflows
app.get('/api/v1/workflows', (req, res) => {
  res.json([
    {
      workflow_id: 'wf-9812',
      status: 'completed',
      objective: 'Multi-Model Routing Validation & Benchmarking',
      current_step: 'complete',
      total_cost_cents: 340,
      duration_ms: 4230,
      started_at: new Date(Date.now() - 300000).toISOString(),
      completed_at: new Date().toISOString(),
      steps: [
        { step_id: 's1', agent_role: 'ceo', action: 'Deconstruct objective into milestones', status: 'completed', duration_ms: 1200, cost_cents: 45, logs: 'Milestones generated cleanly.' },
        { step_id: 's2', agent_role: 'cto', action: 'Design technical specifications and schemas', status: 'completed', duration_ms: 1800, cost_cents: 120, logs: 'Schema validated with Zod & TS.' },
        { step_id: 's3', agent_role: 'engineer', action: 'Implement code modules and unit tests', status: 'completed', duration_ms: 1230, cost_cents: 175, logs: '14 test suites passing.' },
      ],
    },
    {
      workflow_id: 'wf-9813',
      status: 'running',
      objective: 'Autonomous Daily Code Audit & Dependency Upgrade',
      current_step: 'security_fuzzing',
      total_cost_cents: 180,
      duration_ms: 2100,
      started_at: new Date(Date.now() - 60000).toISOString(),
      completed_at: null,
      steps: [
        { step_id: 's1', agent_role: 'devops', action: 'Fetch upstream CVE registry updates', status: 'completed', duration_ms: 900, cost_cents: 30, logs: 'Registry fetched.' },
        { step_id: 's2', agent_role: 'qa', action: 'Execute AST vulnerability scanner', status: 'running', duration_ms: 1200, cost_cents: 150, logs: 'Scanning 142 modules...' },
      ],
    },
  ]);
});

app.post('/api/v1/workflows/:wfId/retry', (req, res) => {
  res.json({ message: `Workflow ${req.params.wfId} restarted from failed step`, status: 'running' });
});

// ──────────────── Vite Middleware & Production Serving ────────────────

async function startServer() {
  if (process.env.NODE_ENV !== 'production') {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: 'spa',
    });
    app.use(vite.middlewares);
    app.use('*', async (req, res, next) => {
      if (req.originalUrl.startsWith('/api/')) return next();
      try {
        const url = req.originalUrl;
        let template = fs.readFileSync(path.resolve(process.cwd(), 'index.html'), 'utf-8');
        template = await vite.transformIndexHtml(url, template);
        res.status(200).set({ 'Content-Type': 'text/html' }).end(template);
      } catch (e) {
        vite.ssrFixStacktrace(e as Error);
        next(e);
      }
    });
  } else {
    const distPath = path.join(process.cwd(), 'dist');
    app.use(express.static(distPath));
    app.get('*', (req, res) => {
      res.sendFile(path.join(distPath, 'index.html'));
    });
  }

  app.listen(PORT, '0.0.0.0', () => {
    console.log(`NEXUS Mission Control server running at http://0.0.0.0:${PORT}`);
  });
}

startServer().catch((err) => {
  console.error('Failed to start server:', err);
  process.exit(1);
});
