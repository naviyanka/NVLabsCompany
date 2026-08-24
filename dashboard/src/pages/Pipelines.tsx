import { useState, useEffect, useMemo } from 'react';
import {
  GitPullRequest,
  Play,
  Clock,
  Plus,
  ShieldCheck,
  Search,
  ListCheck,
  LayoutGrid,
  CheckCircle2,
  Lock,
  Workflow,
  Pencil,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient, unwrapItems } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { PipelineItem, CanvasNode, CanvasEdge, PipelineStage } from '@/types/pipeline';
import { AddPipelineModal } from '@/components/pipelines/AddPipelineModal';
import { PipelineDetailDrawer } from '@/components/pipelines/PipelineDetailDrawer';
import { PipelineBuilderCanvas } from '@/components/pipelines/PipelineBuilderCanvas';

const INITIAL_PIPELINES: PipelineItem[] = [
  {
    id: 'pipe-release',
    name: 'Production Continuous Delivery & Automated PR Gateway',
    description: 'Automated code review, AST impact analysis, security fuzzing, gVisor microVM evaluation, and canary rollout.',
    status: 'completed',
    success_rate: 98.4,
    trigger: 'Webhook / Git Push',
    last_run: new Date(Date.now() - 1800000).toISOString(),
    stages: [
      { id: 'node-1', name: '1. Event Ingest & AST Analysis', assignedAgent: 'Atlas-01', status: 'completed', duration_ms: 450, logs: 'AST parse tree built clean.' },
      { id: 'node-2', name: '2. Code Review & Impact Check', assignedAgent: 'Nova-02', status: 'completed', duration_ms: 1200, logs: 'GitNexus impact analysis verified zero breaking changes.' },
      { id: 'node-3', name: '3. Security Gate Audit', assignedAgent: 'Sentinel-07', status: 'completed', duration_ms: 850, logs: 'gVisor microVM syscall filtering clean.' },
      { id: 'node-4', name: '4. Unit & Integration Testing', assignedAgent: 'Bolt-03', status: 'completed', duration_ms: 1400, logs: 'PASS 18 test suites.' },
    ],
  },
  {
    id: 'pipe-idx',
    name: 'Zero-Trust Threat Intelligence & Webhook Auto-Indexer',
    description: 'Extract semantic embeddings, audit public webhooks for SSRF risks, and store graph relations.',
    status: 'idle',
    success_rate: 100.0,
    trigger: 'Cron Schedule (Hourly)',
    last_run: new Date(Date.now() - 7200000).toISOString(),
    stages: [
      { id: 'node-k1', name: '1. Webhook Vulnerability Audit', assignedAgent: 'Sentinel-07', status: 'completed', duration_ms: 600, logs: 'Audit finished clean.' },
      { id: 'node-k2', name: '2. Extract Vector Embeddings', assignedAgent: 'Sage-05', status: 'completed', duration_ms: 950, logs: 'pgvector memory bank indexed.' },
    ],
  },
];

export function Pipelines() {
  const [pipelines, setPipelines] = useState<PipelineItem[]>(INITIAL_PIPELINES);
  const [agents, setAgents] = useState<{ id: string; name: string; role: string }[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineItem | null>(INITIAL_PIPELINES[0] || null);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);

  const [showAddModal, setShowAddModal] = useState(false);
  const [activeDrawerPipeline, setActiveDrawerPipeline] = useState<PipelineItem | null>(null);
  const [viewMode, setViewMode] = useState<'split' | 'builder' | 'matrix' | 'security'>('split');
  const [search, setSearch] = useState('');
  const [triggerFilter, setTriggerFilter] = useState('all');

  // Visual Builder state
  const [builderPipeline, setBuilderPipeline] = useState<PipelineItem | null>(null);
  const [showBuilder, setShowBuilder] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const res = await apiClient.get<PipelineItem[] | { items: PipelineItem[] }>(
          `/api/v1/companies/${companyId}/pipelines`
        );
        const items = unwrapItems(res);
        if (items.length > 0) {
          setPipelines(items);
          const first = items[0];
          if (first) setSelectedPipeline(first);
        }

        const agentsRes = await apiClient.get<any[] | { items: any[] }>(
          `/api/v1/companies/${companyId}/agents`
        );
        const agentItems = unwrapItems(agentsRes);
        if (agentItems.length) setAgents(agentItems);
      } catch (err) {
        console.error('Failed to load pipelines', err);
      }
    }
    loadData();
  }, []);

  const handlePipelineAdded = (newPipe: PipelineItem) => {
    setPipelines((prev) => [...prev, newPipe]);
    setSelectedPipeline(newPipe);
  };

  const handlePipelineUpdated = (updatedPipe: PipelineItem) => {
    setPipelines((prev) => prev.map((p) => (p.id === updatedPipe.id ? updatedPipe : p)));
    if (selectedPipeline?.id === updatedPipe.id) {
      setSelectedPipeline(updatedPipe);
    }
  };

  const handlePipelineDeleted = (pipeId: string) => {
    setPipelines((prev) => prev.filter((p) => p.id !== pipeId));
    if (selectedPipeline?.id === pipeId) {
      setSelectedPipeline(pipelines.find((p) => p.id !== pipeId) || null);
    }
  };

  const handleTrigger = async (pipeId: string) => {
    setTriggeringId(pipeId);
    const target = pipelines.find((p) => p.id === pipeId);
    if (!target) return;

    const stages = target.stages || [];
    const updatedStages = stages.map((s, idx) => ({
      ...s,
      status: idx === 0 ? ('running' as const) : ('pending' as const),
    }));

    const runningPipe: PipelineItem = {
      ...target,
      status: 'running',
      stages: updatedStages,
      last_run: new Date().toISOString(),
    };

    handlePipelineUpdated(runningPipe);

    let currentIdx = 0;
    const interval = setInterval(() => {
      if (currentIdx < stages.length) {
        const nextStages = stages.map((st, i) => {
          if (i <= currentIdx) {
            return {
              ...st,
              status: 'completed' as const,
              duration_ms: Math.floor(400 + Math.random() * 800),
              logs: `[Stage Executed Cleanly]\n✔ Agent '${st.assignedAgent}' completed stage '${st.name}'`,
            };
          }
          if (i === currentIdx + 1) {
            return { ...st, status: 'running' as const };
          }
          return st;
        });

        const isFinished = currentIdx === stages.length - 1;
        handlePipelineUpdated({
          ...target,
          status: isFinished ? 'completed' : 'running',
          stages: nextStages,
          last_run: new Date().toISOString(),
        });
        currentIdx++;
      } else {
        clearInterval(interval);
        setTriggeringId(null);
      }
    }, 1000);
  };

  const filteredPipelines = useMemo(() => {
    return pipelines.filter((p) => {
      if (triggerFilter !== 'all' && !p.trigger.toLowerCase().includes(triggerFilter.toLowerCase())) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          p.name.toLowerCase().includes(q) ||
          p.trigger.toLowerCase().includes(q) ||
          (p.description || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [pipelines, triggerFilter, search]);

  /* ── Visual builder callbacks ── */
  const openBuilderNew = () => {
    setBuilderPipeline(null);
    setShowBuilder(true);
  };

  const openBuilderEdit = (pipe: PipelineItem) => {
    setBuilderPipeline(pipe);
    setShowBuilder(true);
  };

  const handleBuilderSave = async (canvasNodes: CanvasNode[], canvasEdges: CanvasEdge[], name: string) => {
    // Convert canvas nodes to PipelineStages for backward compat
    const stages: PipelineStage[] = canvasNodes.map((n) => ({
      id: n.id,
      name: n.label,
      assignedAgent: n.agent || 'Atlas-01',
      status: 'pending' as const,
    }));

    if (builderPipeline) {
      // Update existing
      const updated: PipelineItem = {
        ...builderPipeline,
        name,
        stages,
        canvas_nodes: canvasNodes,
        canvas_edges: canvasEdges,
      };
      handlePipelineUpdated(updated);
      try {
        await apiClient.patch(
          `/api/v1/companies/${getActiveCompanyId()}/pipelines/${builderPipeline.id}`,
          { name, stages, canvas_nodes: canvasNodes, canvas_edges: canvasEdges }
        );
      } catch { /* fallback */ }
    } else {
      // Create new
      const newPipe: PipelineItem = {
        id: `pipe-${Date.now().toString(36)}`,
        name,
        description: `Visual pipeline with ${canvasNodes.length} nodes`,
        status: 'idle',
        success_rate: 100,
        trigger: 'Manual Operator Dispatch',
        stages,
        canvas_nodes: canvasNodes,
        canvas_edges: canvasEdges,
        last_run: new Date().toISOString(),
      };
      try {
        const created = await apiClient.post<PipelineItem>(
          `/api/v1/companies/${getActiveCompanyId()}/pipelines`,
          newPipe
        );
        handlePipelineAdded(created);
      } catch {
        handlePipelineAdded(newPipe);
      }
    }
    setShowBuilder(false);
  };

  /* ── Full-screen visual builder ── */
  if (showBuilder) {
    return (
      <PipelineBuilderCanvas
        pipeline={builderPipeline}
        onSave={handleBuilderSave}
        onClose={() => setShowBuilder(false)}
      />
    );
  }

  return (
    <div className="space-y-6 font-sans">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <GitPullRequest className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Continuous Agent CI/CD & Automated PR Gateways
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Automated multi-agent execution graphs, PR review automation, and gVisor zero-trust gates
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<Workflow size={15} />}
            onClick={openBuilderNew}
          >
            Visual Builder
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={15} />}
            onClick={() => setShowAddModal(true)}
          >
            New Pipeline
          </Button>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Active Pipelines</span>
            <GitPullRequest size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">{pipelines.length}</div>
          <p className="text-[10px] text-gray-500 mt-1">Execution graphs nominal</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Aggregate SLA</span>
            <ShieldCheck size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">99.2%</div>
          <p className="text-[10px] text-gray-500 mt-1">1,240 runs MTD</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Mean Execution</span>
            <Clock size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">1m 42s</div>
          <p className="text-[10px] text-gray-500 mt-1">Parallel dispatch</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Security Gates</span>
            <Lock size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">100%</div>
          <p className="text-[10px] text-gray-500 mt-1">Zero vulnerabilities</p>
        </div>
      </div>

      {/* Filter & View Mode Control Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-[#101012] p-3 border border-white/[0.08] rounded-[8px]">
        {/* Search */}
        <div className="relative flex-1 max-w-sm">
          <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search pipelines..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Trigger Filters */}
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {['all', 'Webhook', 'Cron', 'Manual'].map((trig) => (
            <button
              key={trig}
              onClick={() => setTriggerFilter(trig)}
              className={`px-2.5 py-1 rounded text-xs font-mono transition-colors cursor-pointer capitalize whitespace-nowrap ${
                triggerFilter === trig
                  ? 'bg-[#FFB020] text-black font-bold'
                  : 'bg-[#141416] text-[#6B6B6E] hover:text-white border border-white/[0.08]'
              }`}
            >
              {trig === 'all' ? 'All' : trig}
            </button>
          ))}
        </div>

        {/* View Switcher */}
        <div className="flex items-center bg-[#141416] border border-white/[0.08] rounded p-0.5">
          {([
            { key: 'split', icon: <LayoutGrid size={13} />, label: 'Graph' },
            { key: 'builder', icon: <Workflow size={13} />, label: 'Builder' },
            { key: 'matrix', icon: <ListCheck size={13} />, label: 'History' },
            { key: 'security', icon: <ShieldCheck size={13} />, label: 'Security' },
          ] as const).map((v) => (
            <button
              key={v.key}
              onClick={() => v.key === 'builder' ? openBuilderNew() : setViewMode(v.key)}
              className={`px-2 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
                viewMode === v.key ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
              }`}
            >
              {v.icon} {v.label}
            </button>
          ))}
        </div>
      </div>

      {/* VIEW 1: SPLIT PANEL */}
      {viewMode === 'split' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column */}
          <div className="lg:col-span-5 space-y-3">
            <div className="text-xs font-mono font-medium text-[#6B6B6E] uppercase px-1">
              Configured Pipelines ({filteredPipelines.length})
            </div>

            <div className="space-y-2.5">
              {filteredPipelines.map((pipe) => {
                const isSelected = selectedPipeline?.id === pipe.id;
                return (
                  <div
                    key={pipe.id}
                    onClick={() => setSelectedPipeline(pipe)}
                    className={`p-4 rounded-[8px] border transition-all cursor-pointer ${
                      isSelected
                        ? 'bg-[#18181B] border-[#FFB020] shadow-md'
                        : 'bg-[#141416] border-white/[0.08] hover:border-white/[0.2]'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-xs font-medium text-[#F2F1EE]">{pipe.name}</h3>
                      <Badge variant={pipe.status === 'running' ? 'in_progress' : 'completed'}>
                        {pipe.status}
                      </Badge>
                    </div>

                    <div className="mt-3 flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                      <span>Trigger: {pipe.trigger}</span>
                      <span className="text-[#22C55E] font-bold">{pipe.success_rate}% SLA</span>
                    </div>

                    <div className="mt-3 pt-3 border-t border-white/[0.04] flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <button
                          onClick={(e) => { e.stopPropagation(); setActiveDrawerPipeline(pipe); }}
                          className="text-[10px] font-mono text-[#FFB020] hover:underline cursor-pointer"
                        >
                          Inspect →
                        </button>
                        <button
                          onClick={(e) => { e.stopPropagation(); openBuilderEdit(pipe); }}
                          className="text-[10px] font-mono text-cyan-400 hover:underline cursor-pointer flex items-center gap-0.5"
                        >
                          <Pencil size={9} /> Edit Visual
                        </button>
                      </div>

                      <Button
                        variant="ghost"
                        size="xs"
                        icon={<Play className="w-3 h-3 text-[#FFB020]" />}
                        loading={triggeringId === pipe.id}
                        onClick={(e) => { e.stopPropagation(); handleTrigger(pipe.id); }}
                      >
                        Run
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Right Column */}
          <div className="lg:col-span-7">
            {selectedPipeline ? (
              <Card
                header={
                  <div className="flex items-center justify-between w-full">
                    <div>
                      <span className="text-xs font-mono font-medium text-[#F2F1EE] uppercase tracking-wider">
                        {selectedPipeline.name}
                      </span>
                      <div className="text-[10px] font-mono text-[#6B6B6E] mt-0.5">
                        Trigger: {selectedPipeline.trigger}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button variant="secondary" size="xs" icon={<Pencil size={12} />} onClick={() => openBuilderEdit(selectedPipeline)}>
                        Edit in Builder
                      </Button>
                      <Button
                        variant="primary" size="xs" icon={<Play className="w-3 h-3" />}
                        loading={triggeringId === selectedPipeline.id}
                        onClick={() => handleTrigger(selectedPipeline.id)}
                      >
                        Execute
                      </Button>
                    </div>
                  </div>
                }
              >
                <div className="py-4 space-y-4 font-mono text-xs">
                  <div className="text-[10px] text-[#6B6B6E] uppercase tracking-wider">
                    Sequential Stage Graph
                  </div>

                  <div className="space-y-3">
                    {(selectedPipeline.stages || []).map((stage, idx, arr) => {
                      const isDone = stage.status === 'completed';
                      const isRunning = stage.status === 'running';
                      return (
                        <div key={stage.id} className="relative">
                          <div className={`p-3.5 border rounded-[6px] flex items-center justify-between transition-colors ${
                            isDone ? 'bg-[#101012] border-emerald-500/30' : isRunning ? 'bg-[#FFB020]/10 border-[#FFB020] animate-pulse' : 'bg-[#101012] border-white/[0.06]'
                          }`}>
                            <div className="flex items-center gap-3">
                              <div className="w-6 h-6 rounded-[4px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-xs text-[#FFB020]">
                                {idx + 1}
                              </div>
                              <div>
                                <div className="text-xs font-medium text-[#F2F1EE]">{stage.name}</div>
                                <div className="text-[10px] text-[#6B6B6E]">
                                  Agent: <span className="text-[#FFB020]">{stage.assignedAgent}</span>
                                </div>
                              </div>
                            </div>
                            <Badge variant={stage.status as any}>{stage.status}</Badge>
                          </div>
                          {idx < arr.length - 1 && (
                            <div className="w-0.5 h-3 bg-white/[0.08] ml-6 my-0.5" />
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </Card>
            ) : (
              <div className="p-12 text-center bg-[#141416] border border-white/[0.08] rounded-[10px] text-xs font-mono text-[#6B6B6E]">
                Select a pipeline to inspect.
              </div>
            )}
          </div>
        </div>
      )}

      {/* VIEW 2: EXECUTION HISTORY MATRIX */}
      {viewMode === 'matrix' && (
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4 font-mono text-xs">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div>
              <h3 className="text-sm font-medium text-white uppercase">Pipeline Execution History</h3>
              <p className="text-xs text-gray-500">Log of recent automated multi-agent CI/CD runs</p>
            </div>
            <span className="text-xs font-mono text-emerald-400 font-bold">100% SLA Verified</span>
          </div>

          <div className="space-y-2">
            {pipelines.map((p) => (
              <div key={p.id} className="p-3 bg-[#141416] border border-white/[0.06] rounded-[8px] flex items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                  <CheckCircle2 size={16} className="text-emerald-400 shrink-0" />
                  <div>
                    <div className="text-white font-medium">{p.name}</div>
                    <div className="text-[10px] text-gray-500">Trigger: {p.trigger}</div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <span className="text-emerald-400 font-bold">{p.success_rate}%</span>
                    <div className="text-[10px] text-gray-500">{p.stages?.length || 0} stages</div>
                  </div>
                  <button onClick={() => openBuilderEdit(p)} className="text-[10px] text-cyan-400 hover:underline cursor-pointer flex items-center gap-0.5">
                    <Pencil size={9} /> Edit
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* VIEW 3: SECURITY GATES */}
      {viewMode === 'security' && (
        <div className="space-y-4 font-mono text-xs">
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2 mb-1">
              <Lock className="w-4 h-4 text-emerald-400" />
              Automated CI/CD Security Gate Rules & Policies
            </h3>
            <p className="text-xs text-gray-400">
              All pull requests and code changes pass strict security policies before merge
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
              <div className="text-emerald-400 font-bold">1. gVisor MicroVM Sandbox</div>
              <p className="text-gray-400 text-[11px] leading-relaxed">
                Unit test execution runs inside non-root microVM containers with zero syscall bypass access.
              </p>
            </div>
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
              <div className="text-emerald-400 font-bold">2. GitNexus Impact Analysis</div>
              <p className="text-gray-400 text-[11px] leading-relaxed">
                AST impact analysis solver evaluates blast radius on upstream functions.
              </p>
            </div>
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
              <div className="text-emerald-400 font-bold">3. SAST & Webhook SSRF Audit</div>
              <p className="text-gray-400 text-[11px] leading-relaxed">
                Sentinel-07 audits all outbound webhooks and SQL queries for tenant isolation.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Detail Drawer */}
      <PipelineDetailDrawer
        pipeline={activeDrawerPipeline}
        onClose={() => setActiveDrawerPipeline(null)}
        onPipelineUpdated={handlePipelineUpdated}
        onPipelineDeleted={handlePipelineDeleted}
      />

      {/* Form-based Add Modal */}
      <AddPipelineModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onPipelineAdded={handlePipelineAdded}
        agents={agents}
      />
    </div>
  );
}
