import {
  MemoryCluster,
  MemoryGraphData,
  MemoryGraphLink,
  MemoryGraphNode,
  MemoryNodeType,
  MemoryEdgeType,
} from '@/types/memoryGraph';

export const MEMORY_CLUSTERS: MemoryCluster[] = [
  {
    id: 'enterprise_governance',
    name: 'Enterprise Governance & Strategy',
    description: 'Autonomous company OKRs, executive decisions, budget caps, and multi-agent quorum approvals.',
    lead_agent_id: 'agent-atlas',
    color: '#FFB020',
    accent_color: '#F59E0B',
  },
  {
    id: 'systems_routing',
    name: 'Distributed Systems & Model Routing',
    description: 'Multi-provider model routers, fallback circuit breakers, low-latency microservices, and state queues.',
    lead_agent_id: 'agent-nova',
    color: '#38BDF8',
    accent_color: '#0284C7',
  },
  {
    id: 'ai_evolution',
    name: 'AI Research & Prompt Evolution',
    description: 'Empirical prompt mutations, statistical A/B evals, reasoning trees, and vector memory compaction.',
    lead_agent_id: 'agent-sage',
    color: '#A78BFA',
    accent_color: '#8B5CF6',
  },
  {
    id: 'security_audit',
    name: 'Zero-Trust Security & CI/CD Gates',
    description: 'Automated static analysis, HMAC webhook verification, SBOM audits, and regression gates.',
    lead_agent_id: 'agent-shield',
    color: '#34D399',
    accent_color: '#059669',
  },
  {
    id: 'ui_3d_spatial',
    name: 'Spatial Office & Visual Interface',
    description: 'Interactive isometric 3D office floorplan, pixel agents, visual telemetry HUDs, and responsive UI.',
    lead_agent_id: 'agent-pixel',
    color: '#F472B6',
    accent_color: '#DB2777',
  },
  {
    id: 'infrastructure_ops',
    name: 'Cloud Infrastructure & Telemetry',
    description: 'Redis sliding-window rate limiters, container orchestration, uptime monitoring, and latency probes.',
    lead_agent_id: 'agent-forge',
    color: '#FB923C',
    accent_color: '#EA580C',
  },
];

export const NODE_TYPE_COLORS: Record<MemoryNodeType, { bg: string; border: string; text: string; glow: string }> = {
  agent: { bg: '#FFB020', border: '#F59E0B', text: '#0A0A0B', glow: 'rgba(255, 176, 32, 0.4)' },
  goal: { bg: '#38BDF8', border: '#0284C7', text: '#0A0A0B', glow: 'rgba(56, 189, 248, 0.4)' },
  task: { bg: '#34D399', border: '#059669', text: '#0A0A0B', glow: 'rgba(52, 211, 153, 0.4)' },
  knowledge: { bg: '#A78BFA', border: '#7C3AED', text: '#FFFFFF', glow: 'rgba(167, 139, 250, 0.4)' },
  fact: { bg: '#F472B6', border: '#DB2777', text: '#FFFFFF', glow: 'rgba(244, 114, 182, 0.4)' },
  observation: { bg: '#FCD34D', border: '#F59E0B', text: '#0A0A0B', glow: 'rgba(252, 211, 77, 0.4)' },
  experience: { bg: '#818CF8', border: '#4F46E5', text: '#FFFFFF', glow: 'rgba(129, 140, 248, 0.4)' },
  decision: { bg: '#FB923C', border: '#EA580C', text: '#0A0A0B', glow: 'rgba(251, 146, 60, 0.4)' },
  tool_result: { bg: '#2DD4BF', border: '#0D9488', text: '#0A0A0B', glow: 'rgba(45, 212, 191, 0.4)' },
  derived: { bg: '#60A5FA', border: '#2563EB', text: '#FFFFFF', glow: 'rgba(96, 165, 250, 0.4)' },
  contradiction: { bg: '#EF4444', border: '#DC2626', text: '#FFFFFF', glow: 'rgba(239, 68, 68, 0.6)' },
};

export const EDGE_TYPE_COLORS: Record<MemoryEdgeType, { stroke: string; label: string; style: 'solid' | 'dashed' }> = {
  depends_on: { stroke: '#38BDF8', label: 'Depends On', style: 'dashed' },
  produced_by: { stroke: '#FFB020', label: 'Produced By', style: 'solid' },
  supports: { stroke: '#34D399', label: 'Supports / Evidences', style: 'solid' },
  contradicts: { stroke: '#EF4444', label: 'Contradicts / Conflicts', style: 'dashed' },
  derived_from: { stroke: '#A78BFA', label: 'Derived From', style: 'solid' },
  informs: { stroke: '#60A5FA', label: 'Informs / Guides', style: 'solid' },
  part_of: { stroke: '#6B6B6E', label: 'Part Of', style: 'solid' },
  temporal_precedes: { stroke: '#F59E0B', label: 'Temporal Precedes', style: 'dashed' },
};

function generateEmbeddingPreview(): number[] {
  return Array.from({ length: 8 }, () => Number((Math.random() * 2 - 1).toFixed(4)));
}

const INITIAL_NODES: MemoryGraphNode[] = [
  // ── AGENTS ──
  {
    id: 'agent-atlas',
    label: 'Atlas-01 (CEO)',
    type: 'agent',
    community: 'enterprise_governance',
    agent_id: 'agent-atlas',
    importance: 0.98,
    confidence: 0.99,
    created_at: new Date(Date.now() - 30 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Executive reasoning core coordinating company objectives, budget policies, and governance approvals.',
    tags: ['executive', 'governance', 'strategy'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 840,
    decay_score: 1.0,
  },
  {
    id: 'agent-nova',
    label: 'Nova-02 (CTO)',
    type: 'agent',
    community: 'systems_routing',
    agent_id: 'agent-nova',
    importance: 0.96,
    confidence: 0.98,
    created_at: new Date(Date.now() - 28 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Lead system architect governing API schemas, microservice decoupled contracts, and technical roadmap.',
    tags: ['architecture', 'system-design', 'backend'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 720,
    decay_score: 1.0,
  },
  {
    id: 'agent-bolt',
    label: 'Bolt-03 (Backend Eng)',
    type: 'agent',
    community: 'systems_routing',
    agent_id: 'agent-bolt',
    importance: 0.94,
    confidence: 0.95,
    created_at: new Date(Date.now() - 25 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'High-throughput backend engineer implementing Redis rate limiters, model adapters, and circuit breakers.',
    tags: ['fastapi', 'distributed-systems', 'redis'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 650,
    decay_score: 0.96,
  },
  {
    id: 'agent-pixel',
    label: 'Pixel-04 (Frontend Eng)',
    type: 'agent',
    community: 'ui_3d_spatial',
    agent_id: 'agent-pixel',
    importance: 0.92,
    confidence: 0.94,
    created_at: new Date(Date.now() - 25 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Spatial frontend engineer crafting the 3D isometric office, WebGL render passes, and live telemetry UI.',
    tags: ['threejs', 'webgl', 'react', 'tailwind'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 580,
    decay_score: 0.94,
  },
  {
    id: 'agent-sage',
    label: 'Sage-05 (AI Research)',
    type: 'agent',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.97,
    confidence: 0.97,
    created_at: new Date(Date.now() - 20 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'AI researcher optimizing prompt mutations, statistical reasoning trees, and vector memory retrieval recall.',
    tags: ['prompt-evolution', 'evals', 'rag', 'reasoning'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 790,
    decay_score: 0.98,
  },
  {
    id: 'agent-shield',
    label: 'Shield-07 (QA & Sec)',
    type: 'agent',
    community: 'security_audit',
    agent_id: 'agent-shield',
    importance: 0.95,
    confidence: 0.96,
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Zero-trust security and automated regression gatekeeper running vulnerability scans and contract tests.',
    tags: ['security', 'fuzzing', 'ci-cd', 'verification'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 490,
    decay_score: 0.92,
  },
  {
    id: 'agent-forge',
    label: 'Forge-08 (DevOps)',
    type: 'agent',
    community: 'infrastructure_ops',
    agent_id: 'agent-forge',
    importance: 0.93,
    confidence: 0.95,
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Container orchestrator managing Kubernetes deployments, Redis cluster health, and cloud cost telemetry.',
    tags: ['kubernetes', 'docker', 'rate-limit', 'observability'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 410,
    decay_score: 0.91,
  },

  // ── GOALS ──
  {
    id: 'goal-sub50ms',
    label: 'Goal: Sub-50ms Global Model Routing',
    type: 'goal',
    community: 'systems_routing',
    agent_id: 'agent-nova',
    importance: 0.92,
    confidence: 0.88,
    created_at: new Date(Date.now() - 20 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Objective to achieve median routing latency < 35ms and p99 < 50ms across dynamic multi-provider LLM calls.',
    tags: ['okr', 'performance', 'latency', 'routing'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 310,
    decay_score: 0.95,
  },
  {
    id: 'goal-zero-trust',
    label: 'Goal: 100% Automated Security Verification',
    type: 'goal',
    community: 'security_audit',
    agent_id: 'agent-shield',
    importance: 0.94,
    confidence: 0.92,
    created_at: new Date(Date.now() - 15 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Objective ensuring every agent pull request and webhook payload passes zero-trust cryptographic signature and AST security checks.',
    tags: ['okr', 'security', 'zero-trust'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 260,
    decay_score: 0.93,
  },
  {
    id: 'goal-evolution-alpha',
    label: 'Goal: Autonomous Prompt Evolution Alpha',
    type: 'goal',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.90,
    confidence: 0.85,
    created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Establish an automated weekly prompt mutation pipeline with verified statistical confidence intervals (p < 0.05).',
    tags: ['okr', 'evolution', 'evals'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 380,
    decay_score: 0.94,
  },

  // ── TASKS ──
  {
    id: 'task-4471',
    label: 'Task #4471: Multi-Model Router',
    type: 'task',
    community: 'systems_routing',
    agent_id: 'agent-bolt',
    importance: 0.95,
    confidence: 0.96,
    created_at: new Date(Date.now() - 7 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    summary: 'Wire Claude 3.7 and GPT-4o adapter endpoints for dynamic load balancing and circuit breaking.',
    tags: ['task', 'completed', 'routing', 'adapters'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 420,
    decay_score: 0.92,
  },
  {
    id: 'task-4472',
    label: 'Task #4472: 3D Office Floorplan',
    type: 'task',
    community: 'ui_3d_spatial',
    agent_id: 'agent-pixel',
    importance: 0.91,
    confidence: 0.93,
    created_at: new Date(Date.now() - 5 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Render interactive isometric Three.js office zones with realtime agent status avatars and animation paths.',
    tags: ['task', 'in_progress', 'threejs', 'office'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 390,
    decay_score: 0.95,
  },
  {
    id: 'task-4473',
    label: 'Task #4473: Prompt Optimizer Sandbox',
    type: 'task',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.89,
    confidence: 0.91,
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Run A/B evaluation sandbox for agent prompt mutations and measure benchmark accuracy gains.',
    tags: ['task', 'in_progress', 'ab-testing', 'evals'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 275,
    decay_score: 0.97,
  },
  {
    id: 'task-4474',
    label: 'Task #4474: Automated CI/CD Gates',
    type: 'task',
    community: 'security_audit',
    agent_id: 'agent-shield',
    importance: 0.88,
    confidence: 0.94,
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Run static analysis, dependency audit, and fuzz testing on all agent-generated pull requests.',
    tags: ['task', 'pending', 'ci-cd', 'security'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 190,
    decay_score: 0.98,
  },
  {
    id: 'task-4475',
    label: 'Task #4475: Redis Rate Limiter',
    type: 'task',
    community: 'infrastructure_ops',
    agent_id: 'agent-forge',
    importance: 0.87,
    confidence: 0.95,
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Enforce strict 1000 req/min sliding-window token bucket per agent identity with exponential backoff.',
    tags: ['task', 'pending', 'redis', 'rate-limit'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 140,
    decay_score: 0.99,
  },

  // ── KNOWLEDGE ARTICLES ──
  {
    id: 'kb-governance',
    label: 'Standard: Autonomous Governance & Quorum',
    type: 'knowledge',
    community: 'enterprise_governance',
    agent_id: 'agent-atlas',
    importance: 0.96,
    confidence: 0.99,
    created_at: new Date(Date.now() - 28 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    summary: 'Mandates least-privilege agent envelopes, hard spend caps at 80%, and mandatory 2-of-3 quorum for production schema mutations.',
    tags: ['governance', 'quorum', 'budget-caps', 'security'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 512,
    decay_score: 0.97,
  },
  {
    id: 'kb-stats-significance',
    label: 'Standard: Statistical Evals Protocol',
    type: 'knowledge',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.92,
    confidence: 0.97,
    created_at: new Date(Date.now() - 18 * 86400000).toISOString(),
    updated_at: new Date(Date.now() - 5 * 86400000).toISOString(),
    summary: 'Prompt mutation proposals require p < 0.05 and minimum 50 eval runs across standardized reasoning suites before deployment.',
    tags: ['evolution', 'statistics', 'evaluation-standards'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 340,
    decay_score: 0.95,
  },

  // ── HARD FACTS ──
  {
    id: 'fact-redis-p99',
    label: 'Fact: Redis p99 Latency = 1.4ms',
    type: 'fact',
    community: 'infrastructure_ops',
    agent_id: 'agent-forge',
    importance: 0.85,
    confidence: 0.99,
    created_at: new Date(Date.now() - 4 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Redis sliding-window cluster roundtrip benchmark shows 1.4ms p99 latency under 12,500 requests/sec load.',
    tags: ['benchmark', 'redis', 'telemetry', 'hardware'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 220,
    decay_score: 0.93,
  },
  {
    id: 'fact-hmac-cost',
    label: 'Fact: HMAC Verification Overhead = 0.08ms',
    type: 'fact',
    community: 'security_audit',
    agent_id: 'agent-shield',
    importance: 0.82,
    confidence: 0.99,
    created_at: new Date(Date.now() - 8 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'SHA-256 HMAC payload validation introduces only 0.08ms compute overhead per incoming request.',
    tags: ['cryptography', 'hmac', 'overhead'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 180,
    decay_score: 0.89,
  },
  {
    id: 'fact-hnsw-recall',
    label: 'Fact: HNSW Vector Recall = 99.2%',
    type: 'fact',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.89,
    confidence: 0.98,
    created_at: new Date(Date.now() - 6 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'HNSW vector index achieves 99.2% top-5 recall across 4,200 indexed memory embeddings at sub-12ms latency.',
    tags: ['hnsw', 'vector-index', 'recall'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 310,
    decay_score: 0.94,
  },

  // ── OBSERVATIONS ──
  {
    id: 'obs-latency-spike',
    label: 'Obs: Claude Upstream Latency Spike',
    type: 'observation',
    community: 'systems_routing',
    agent_id: 'agent-bolt',
    importance: 0.78,
    confidence: 0.94,
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Observed intermittent 4.2% latency spike and 2 consecutive 503 errors on upstream Claude endpoint at 14:20 UTC.',
    tags: ['telemetry', 'spike', 'upstream', 'circuit-breaker'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 140,
    decay_score: 0.85,
  },
  {
    id: 'obs-cot-token-reduction',
    label: 'Obs: Few-Shot Compaction Saves 32% Tokens',
    type: 'observation',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.88,
    confidence: 0.96,
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Compressing repetitive instructions into structured few-shot demonstrations dropped average token consumption from 1,240 to 843 tokens.',
    tags: ['prompting', 'optimization', 'tokens'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 245,
    decay_score: 0.92,
  },
  {
    id: 'obs-canvas-fps',
    label: 'Obs: Canvas Frame Rate Stabilized at 60 FPS',
    type: 'observation',
    community: 'ui_3d_spatial',
    agent_id: 'agent-pixel',
    importance: 0.80,
    confidence: 0.95,
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Debouncing window resize events and caching sprite transforms sustained a solid 60 FPS across all 8 agent roaming loops.',
    tags: ['threejs', 'fps', 'performance'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 170,
    decay_score: 0.90,
  },

  // ── EXPERIENCES (Episodic Memory) ──
  {
    id: 'exp-multi-model-failover',
    label: 'Exp: Live Failover Circuit Breaker Trip',
    type: 'experience',
    community: 'systems_routing',
    agent_id: 'agent-bolt',
    importance: 0.91,
    confidence: 0.97,
    created_at: new Date(Date.now() - 5 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'When Claude endpoint degraded, circuit breaker autonomously rerouted 150 tasks to GPT-4o in 18ms with 0 dropped payloads.',
    tags: ['incident-resolution', 'circuit-breaker', 'failover'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 360,
    decay_score: 0.91,
  },
  {
    id: 'exp-pr-security-gate',
    label: 'Exp: Blocked Unsanitized Webhook Payload',
    type: 'experience',
    community: 'security_audit',
    agent_id: 'agent-shield',
    importance: 0.89,
    confidence: 0.99,
    created_at: new Date(Date.now() - 7 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Automated CI gate intercepted an incoming webhook with missing HMAC signature and rejected execution before database write.',
    tags: ['security-incident', 'prevention', 'hmac'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 210,
    decay_score: 0.88,
  },

  // ── DECISIONS ──
  {
    id: 'dec-circuit-breaker-threshold',
    label: 'Dec: Set Circuit Breaker to 5 Consecutive 503s',
    type: 'decision',
    community: 'systems_routing',
    agent_id: 'agent-nova',
    importance: 0.94,
    confidence: 0.96,
    created_at: new Date(Date.now() - 4 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Consensus reached between Nova-02 and Bolt-03 to trip fallback router when 5 consecutive upstream 503 errors occur within 10 seconds.',
    tags: ['architecture-decision', 'threshold', 'resilience'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 410,
    decay_score: 0.95,
  },
  {
    id: 'dec-token-bucket-limit',
    label: 'Dec: Standardize on 1000 req/min Per Agent',
    type: 'decision',
    community: 'infrastructure_ops',
    agent_id: 'agent-forge',
    importance: 0.87,
    confidence: 0.95,
    created_at: new Date(Date.now() - 6 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Standardized rate limiting threshold to 1000 requests per minute per agent identity to guarantee budget compliance.',
    tags: ['rate-limit', 'policy', 'budget-guardrail'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 290,
    decay_score: 0.92,
  },

  // ── TOOL RESULTS ──
  {
    id: 'tool-result-git-pr',
    label: 'Tool: GitHub PR #104 CI Verification',
    type: 'tool_result',
    community: 'security_audit',
    agent_id: 'agent-shield',
    importance: 0.84,
    confidence: 0.98,
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Executed 14 automated test suites on PR #104: 100% passed, 0 security warnings, 94.2% test coverage.',
    tags: ['test-result', 'pr-104', 'coverage'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 160,
    decay_score: 0.96,
  },
  {
    id: 'tool-result-vector-query',
    label: 'Tool: Vector Similarity Top-5 Search',
    type: 'tool_result',
    community: 'ai_evolution',
    agent_id: 'agent-sage',
    importance: 0.81,
    confidence: 0.97,
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Queried 5 nearest neighbor memories for prompt candidate #701: cosine similarity 0.941 to baseline benchmarks.',
    tags: ['vector-search', 'cosine-similarity', 'hnsw'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 195,
    decay_score: 0.94,
  },

  // ── DERIVED KNOWLEDGE ──
  {
    id: 'derived-speculative-caching',
    label: 'Derived: Speculative Semantic Caching',
    type: 'derived',
    community: 'systems_routing',
    agent_id: 'agent-bolt',
    importance: 0.93,
    confidence: 0.94,
    created_at: new Date(Date.now() - 3 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Caching high-frequency vector embeddings for recurring squad meeting prompts yields 45% retrieval latency improvement.',
    tags: ['synthesis', 'caching', 'vector-optimization'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 480,
    decay_score: 0.97,
  },
  {
    id: 'derived-idempotent-state',
    label: 'Derived: Idempotent Agent State Transitions',
    type: 'derived',
    community: 'systems_routing',
    agent_id: 'agent-nova',
    importance: 0.91,
    confidence: 0.98,
    created_at: new Date(Date.now() - 10 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Optimistic version checks on task state machines prevent double-execution when workers experience network partitions.',
    tags: ['idempotency', 'distributed-consensus', 'reliability'],
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 320,
    decay_score: 0.93,
  },

  // ── CONTRADICTIONS / CONFLICTING BELIEFS ──
  {
    id: 'conflict-prompt-702',
    label: 'Conflict: Prompt #702 Accuracy Regression',
    type: 'contradiction',
    community: 'ai_evolution',
    agent_id: 'agent-shield',
    importance: 0.93,
    confidence: 0.91,
    created_at: new Date(Date.now() - 1 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Candidate prompt #702 claimed +25% speedup, but automated fuzz tests detected a 12% regression on edge-case schema validation.',
    tags: ['conflict', 'eval-regression', 'anomaly'],
    contradiction_target_id: 'obs-cot-token-reduction',
    contradiction_reason: 'Speed optimization pruned essential guardrail instructions for edge-case typing.',
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 290,
    decay_score: 0.98,
  },
  {
    id: 'conflict-cache-ttl',
    label: 'Conflict: Cache TTL vs Freshness Mandate',
    type: 'contradiction',
    community: 'infrastructure_ops',
    agent_id: 'agent-forge',
    importance: 0.88,
    confidence: 0.89,
    created_at: new Date(Date.now() - 2 * 86400000).toISOString(),
    updated_at: new Date().toISOString(),
    summary: 'Configured 600s cache TTL violates telemetry freshness requirement (<30s) during active live incident reviews.',
    tags: ['conflict', 'ttl-mismatch', 'telemetry'],
    contradiction_target_id: 'derived-speculative-caching',
    contradiction_reason: 'Aggressive 10-minute caching causes stale heartbeat reads in the 3D office telemetry HUD.',
    embedding_dim: 1536,
    embedding_preview: generateEmbeddingPreview(),
    access_count: 220,
    decay_score: 0.95,
  },
];

const INITIAL_LINKS: MemoryGraphLink[] = [
  // Governance & Atlas
  { id: 'l1', source: 'agent-atlas', target: 'kb-governance', type: 'informs', weight: 0.98, label: 'Enforces Governance' },
  { id: 'l2', source: 'agent-atlas', target: 'goal-sub50ms', type: 'depends_on', weight: 0.90, label: 'Strategic Milestone' },
  { id: 'l3', source: 'agent-atlas', target: 'goal-zero-trust', type: 'depends_on', weight: 0.92, label: 'Mandates Policy' },

  // Nova Architecture & Routing
  { id: 'l4', source: 'agent-nova', target: 'agent-bolt', type: 'informs', weight: 0.95, label: 'Delegates Engineering' },
  { id: 'l5', source: 'agent-nova', target: 'goal-sub50ms', type: 'supports', weight: 0.94, label: 'Owns Architecture' },
  { id: 'l6', source: 'agent-nova', target: 'dec-circuit-breaker-threshold', type: 'produced_by', weight: 0.96, label: 'Authored Decision' },
  { id: 'l7', source: 'agent-nova', target: 'derived-idempotent-state', type: 'derived_from', weight: 0.93, label: 'Distilled Principle' },

  // Bolt Microservices & Tasks
  { id: 'l8', source: 'agent-bolt', target: 'task-4471', type: 'produced_by', weight: 0.98, label: 'Executed Task' },
  { id: 'l9', source: 'task-4471', target: 'exp-multi-model-failover', type: 'supports', weight: 0.96, label: 'Verified in Prod' },
  { id: 'l10', source: 'exp-multi-model-failover', target: 'dec-circuit-breaker-threshold', type: 'supports', weight: 0.95, label: 'Empirical Evidence' },
  { id: 'l11', source: 'obs-latency-spike', target: 'exp-multi-model-failover', type: 'temporal_precedes', weight: 0.88, label: 'Triggered Failover' },
  { id: 'l12', source: 'agent-bolt', target: 'derived-speculative-caching', type: 'derived_from', weight: 0.92, label: 'Synthesized Insight' },

  // Sage AI Evolution
  { id: 'l13', source: 'agent-sage', target: 'goal-evolution-alpha', type: 'supports', weight: 0.95, label: 'Leads Evolution' },
  { id: 'l14', source: 'agent-sage', target: 'kb-stats-significance', type: 'informs', weight: 0.96, label: 'Published Standard' },
  { id: 'l15', source: 'agent-sage', target: 'task-4473', type: 'produced_by', weight: 0.92, label: 'Supervises Sandbox' },
  { id: 'l16', source: 'task-4473', target: 'obs-cot-token-reduction', type: 'supports', weight: 0.94, label: 'Measured Outcome' },
  { id: 'l17', source: 'agent-sage', target: 'fact-hnsw-recall', type: 'supports', weight: 0.95, label: 'Benchmarked HNSW' },
  { id: 'l18', source: 'task-4473', target: 'tool-result-vector-query', type: 'produced_by', weight: 0.91, label: 'Ran Vector Query' },

  // Shield Security & CI/CD
  { id: 'l19', source: 'agent-shield', target: 'goal-zero-trust', type: 'supports', weight: 0.96, label: 'Enforces Zero-Trust' },
  { id: 'l20', source: 'agent-shield', target: 'task-4474', type: 'produced_by', weight: 0.94, label: 'Executes Gates' },
  { id: 'l21', source: 'agent-shield', target: 'fact-hmac-cost', type: 'supports', weight: 0.92, label: 'Measured Micro-bench' },
  { id: 'l22', source: 'task-4474', target: 'tool-result-git-pr', type: 'produced_by', weight: 0.95, label: 'Ran CI Suite' },
  { id: 'l23', source: 'task-4474', target: 'exp-pr-security-gate', type: 'supports', weight: 0.93, label: 'Intercepted Threat' },

  // Forge Infrastructure & Redis
  { id: 'l24', source: 'agent-forge', target: 'task-4475', type: 'produced_by', weight: 0.94, label: 'Deploys Redis' },
  { id: 'l25', source: 'agent-forge', target: 'fact-redis-p99', type: 'supports', weight: 0.95, label: 'Monitored Latency' },
  { id: 'l26', source: 'task-4475', target: 'dec-token-bucket-limit', type: 'supports', weight: 0.92, label: 'Implements Policy' },
  { id: 'l27', source: 'task-4475', target: 'goal-sub50ms', type: 'supports', weight: 0.89, label: 'Underpins SLA' },

  // Pixel Frontend & Spatial
  { id: 'l28', source: 'agent-pixel', target: 'task-4472', type: 'produced_by', weight: 0.95, label: 'Built 3D Floorplan' },
  { id: 'l29', source: 'task-4472', target: 'obs-canvas-fps', type: 'supports', weight: 0.93, label: 'Measured Frame Rate' },

  // Cross-Cluster Dependencies & Derived Relationships
  { id: 'l30', source: 'derived-speculative-caching', target: 'goal-sub50ms', type: 'supports', weight: 0.94, label: 'Accelerates Latency' },
  { id: 'l31', source: 'fact-hnsw-recall', target: 'derived-speculative-caching', type: 'derived_from', weight: 0.92, label: 'Vector Index Basis' },
  { id: 'l32', source: 'fact-redis-p99', target: 'goal-sub50ms', type: 'supports', weight: 0.90, label: 'Low Latency State' },

  // Contradiction Edges
  {
    id: 'l33',
    source: 'conflict-prompt-702',
    target: 'obs-cot-token-reduction',
    type: 'contradicts',
    weight: 0.95,
    label: 'Flags Regression',
    is_contradiction: true,
    is_active: true,
  },
  {
    id: 'l34',
    source: 'conflict-cache-ttl',
    target: 'derived-speculative-caching',
    type: 'contradicts',
    weight: 0.92,
    label: 'Conflicts with Freshness',
    is_contradiction: true,
    is_active: true,
  },
];

class MemoryGraphStore {
  private data: MemoryGraphData;
  private listeners: Set<() => void> = new Set();

  constructor() {
    this.data = this.calculateInitialData();
  }

  private calculateInitialData(): MemoryGraphData {
    const nodes = JSON.parse(JSON.stringify(INITIAL_NODES)) as MemoryGraphNode[];
    const links = JSON.parse(JSON.stringify(INITIAL_LINKS)) as MemoryGraphLink[];
    const clusters = JSON.parse(JSON.stringify(MEMORY_CLUSTERS)) as MemoryCluster[];

    const contradictions_count = nodes.filter((n) => n.type === 'contradiction').length;
    const avg_confidence = Number(
      (nodes.reduce((sum, n) => sum + n.confidence, 0) / nodes.length).toFixed(3)
    );
    const avg_importance = Number(
      (nodes.reduce((sum, n) => sum + n.importance, 0) / nodes.length).toFixed(3)
    );

    return {
      nodes,
      links,
      clusters,
      metrics: {
        total_nodes: nodes.length,
        total_links: links.length,
        contradictions_count,
        avg_confidence,
        avg_importance,
        modularity_score: 0.78,
        clustering_coefficient: 0.64,
        memory_recall_rate: 99.2,
        hnsw_index_size_kb: 4820,
      },
    };
  }

  public getData(): MemoryGraphData {
    return this.data;
  }

  public subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private notify() {
    this.listeners.forEach((l) => l());
  }

  public addNode(nodeData: Partial<MemoryGraphNode> & { label: string; type: MemoryNodeType; community: MemoryCluster['id'] }) {
    const id = nodeData.id || `node-${Date.now().toString(36)}`;
    const newNode: MemoryGraphNode = {
      id,
      label: nodeData.label,
      type: nodeData.type,
      community: nodeData.community,
      agent_id: nodeData.agent_id || 'agent-atlas',
      importance: nodeData.importance ?? 0.85,
      confidence: nodeData.confidence ?? 0.92,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      summary: nodeData.summary || nodeData.label,
      raw_content: nodeData.raw_content,
      tags: nodeData.tags || ['custom', nodeData.type],
      embedding_dim: 1536,
      embedding_preview: generateEmbeddingPreview(),
      access_count: 1,
      decay_score: 1.0,
      contradiction_target_id: nodeData.contradiction_target_id,
      contradiction_reason: nodeData.contradiction_reason,
    };

    this.data.nodes.unshift(newNode);

    // If provenance sources or target exists, link them
    if (nodeData.contradiction_target_id) {
      this.data.links.push({
        id: `link-conflict-${Date.now()}`,
        source: newNode.id,
        target: nodeData.contradiction_target_id,
        type: 'contradicts',
        weight: 0.95,
        label: 'Conflicting Belief',
        is_contradiction: true,
        is_active: true,
      });
    }

    this.recalculateMetrics();
    this.notify();
    return newNode;
  }

  public addLink(linkData: { source: string; target: string; type: MemoryEdgeType; label?: string; weight?: number }) {
    const newLink: MemoryGraphLink = {
      id: `link-${Date.now().toString(36)}`,
      source: linkData.source,
      target: linkData.target,
      type: linkData.type,
      weight: linkData.weight ?? 0.85,
      label: linkData.label || linkData.type.replace('_', ' '),
      is_contradiction: linkData.type === 'contradicts',
      is_active: linkData.type === 'contradicts',
    };

    this.data.links.push(newLink);
    this.recalculateMetrics();
    this.notify();
    return newLink;
  }

  public reinforceNode(nodeId: string) {
    const node = this.data.nodes.find((n) => n.id === nodeId);
    if (node) {
      node.access_count = (node.access_count || 0) + 10;
      node.decay_score = 1.0;
      node.importance = Math.min(1.0, node.importance + 0.05);
      node.confidence = Math.min(1.0, node.confidence + 0.02);
      node.updated_at = new Date().toISOString();
      this.recalculateMetrics();
      this.notify();
    }
  }

  public resolveContradiction(contradictionNodeId: string, resolutionAction: 'prune' | 'override' | 'archive') {
    if (resolutionAction === 'prune') {
      this.data.nodes = this.data.nodes.filter((n) => n.id !== contradictionNodeId);
      this.data.links = this.data.links.filter((l) => {
        const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
        const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
        return sId !== contradictionNodeId && tId !== contradictionNodeId;
      });
    } else {
      const node = this.data.nodes.find((n) => n.id === contradictionNodeId);
      if (node) {
        node.type = 'derived';
        node.summary = `[Resolved] ${node.summary}`;
        node.tags.push('resolved');
      }
      // deactivate contradiction link
      this.data.links.forEach((l) => {
        const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
        if (sId === contradictionNodeId) {
          l.is_contradiction = false;
          l.is_active = false;
          l.type = 'supports';
        }
      });
    }
    this.recalculateMetrics();
    this.notify();
  }

  public pruneDecayedNodes(threshold: number = 0.5) {
    const initialCount = this.data.nodes.length;
    // Don't prune agents, goals, or core knowledge
    this.data.nodes = this.data.nodes.filter((n) => {
      if (['agent', 'goal', 'knowledge'].includes(n.type)) return true;
      return (n.decay_score ?? 1.0) >= threshold;
    });

    const activeIds = new Set(this.data.nodes.map((n) => n.id));
    this.data.links = this.data.links.filter((l) => {
      const sId = typeof l.source === 'object' ? (l.source as MemoryGraphNode).id : l.source;
      const tId = typeof l.target === 'object' ? (l.target as MemoryGraphNode).id : l.target;
      return activeIds.has(sId) && activeIds.has(tId);
    });

    this.recalculateMetrics();
    this.notify();
    return initialCount - this.data.nodes.length;
  }

  private recalculateMetrics() {
    const nodes = this.data.nodes;
    const links = this.data.links;
    this.data.metrics = {
      total_nodes: nodes.length,
      total_links: links.length,
      contradictions_count: nodes.filter((n) => n.type === 'contradiction').length,
      avg_confidence: Number((nodes.reduce((s, n) => s + n.confidence, 0) / nodes.length).toFixed(3)),
      avg_importance: Number((nodes.reduce((s, n) => s + n.importance, 0) / nodes.length).toFixed(3)),
      modularity_score: 0.78,
      clustering_coefficient: 0.64,
      memory_recall_rate: 99.2,
      hnsw_index_size_kb: Math.round(nodes.length * 180 + 800),
    };
  }
}

export const memoryGraphStore = new MemoryGraphStore();
