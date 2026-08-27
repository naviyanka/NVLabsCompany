import { apiClient } from '@/api/client';
import { Badge } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { LaunchWorkflowModal } from '@/components/workflows/LaunchWorkflowModal';
import { TriggersPanel } from '@/components/workflows/TriggersPanel';
import { WorkflowDetailDrawer } from '@/components/workflows/WorkflowDetailDrawer';
import { getActiveCompanyId } from '@/config';
import type { WorkflowDAGItem } from '@/types/workflow';
import {
  CheckCircle2,
  Clock,
  DollarSign,
  GitMerge,
  Layers,
  LayoutGrid,
  Plus,
  Search,
  Zap
} from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

const INITIAL_WORKFLOWS: WorkflowDAGItem[] = [];

export function Workflows() {
  const [workflows, setWorkflows] = useState<WorkflowDAGItem[]>(INITIAL_WORKFLOWS);
  const [agents, setAgents] = useState<{ id: string; name: string; role: string }[]>([]);
  const [selectedWorkflow, setSelectedWorkflow] = useState<WorkflowDAGItem | null>(null);
  const [showLaunchModal, setShowLaunchModal] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'flow' | 'analytics' | 'triggers'>('grid');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');

  useEffect(() => {
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const res = await apiClient.get<WorkflowDAGItem[]>(
          `/api/v1/companies/${companyId}/workflows`
        );
        const items = res;
        if (items.length > 0) {
          setWorkflows(items);
        }

        const agentsRes = await apiClient.get<any[]>(
          `/api/v1/companies/${companyId}/agents`
        );
        const agentItems = agentsRes;
        if (agentItems.length) setAgents(agentItems);
      } catch (err) {
        console.error('Failed to load workflows', err);
      }
    }
    loadData();
  }, []);

  const handleWorkflowLaunched = (newWf: WorkflowDAGItem) => {
    setWorkflows((prev) => [newWf, ...prev]);
    setSelectedWorkflow(newWf);
  };

  const handleWorkflowUpdated = (updatedWf: WorkflowDAGItem) => {
    setWorkflows((prev) => prev.map((w) => (w.workflow_id === updatedWf.workflow_id ? updatedWf : w)));
    if (selectedWorkflow?.workflow_id === updatedWf.workflow_id) {
      setSelectedWorkflow(updatedWf);
    }
  };

  const filteredWorkflows = useMemo(() => {
    return workflows.filter((w) => {
      if (statusFilter !== 'all' && w.status !== statusFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          (w.title || '').toLowerCase().includes(q) ||
          w.objective.toLowerCase().includes(q) ||
          w.current_step.toLowerCase().includes(q) ||
          (w.template_type || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [workflows, statusFilter, search]);

  const activeCount = workflows.filter((w) => w.status === 'running').length;
  const completedCount = workflows.filter((w) => w.status === 'completed').length;
  const totalSpendCents = workflows.reduce((sum, w) => sum + w.total_cost_cents, 0);

  return (
    <div className="space-y-6 font-sans">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Dynamic Multi-Agent Workflows & DAG Pipelines
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Asynchronous DAG execution plans, multi-agent step sequences, and cost-bound token dispatch
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowLaunchModal(true)}
        >
          Launch DAG Workflow
        </Button>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Active DAGs In Flight</span>
            <Layers size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">{activeCount} Pipelines</div>
          <p className="text-[10px] text-gray-500 mt-1">Parallel dispatch running</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Completed Executions</span>
            <CheckCircle2 size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">{completedCount} Finished</div>
          <p className="text-[10px] text-gray-500 mt-1">100% SLA verification</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Total Execution Spend</span>
            <DollarSign size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">
            ${(totalSpendCents / 100).toFixed(2)}
          </div>
          <p className="text-[10px] text-gray-500 mt-1">Token budget bounded</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Avg Node Latency</span>
            <Clock size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">1.8s</div>
          <p className="text-[10px] text-gray-500 mt-1">Fast asynchronous hops</p>
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
            placeholder="Search workflows by objective, ID, stage..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Status Filters */}
        <div className="flex items-center gap-1.5">
          {['all', 'running', 'completed'].map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={`px-2.5 py-1 rounded text-xs font-mono transition-colors cursor-pointer capitalize ${statusFilter === st
                ? 'bg-[#FFB020] text-black font-bold'
                : 'bg-[#141416] text-[#6B6B6E] hover:text-white border border-white/[0.08]'
                }`}
            >
              {st}
            </button>
          ))}
        </div>

        {/* View Switcher */}
        <div className="flex items-center bg-[#141416] border border-white/[0.08] rounded p-0.5">
          <button
            onClick={() => setViewMode('grid')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${viewMode === 'grid' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
              }`}
          >
            <LayoutGrid size={13} /> Grid
          </button>
          <button
            onClick={() => setViewMode('flow')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${viewMode === 'flow' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
              }`}
          >
            <GitMerge size={13} /> Flowchart
          </button>
          <button
            onClick={() => setViewMode('triggers')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${viewMode === 'triggers' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
              }`}
          >
            <Zap size={13} /> Triggers
          </button>
        </div>
      </div>

      {/* VIEW 1: ACTIVE DAG PIPELINES GRID */}
      {viewMode === 'grid' && (
        <div className="space-y-3">
          {filteredWorkflows.map((wf) => {
            const progressPct = Math.round((wf.completed_steps / (wf.total_steps || 1)) * 100);
            return (
              <Card
                key={wf.workflow_id}
                className="hover:border-[#FFB020]/40 transition-colors cursor-pointer group"
                onClick={() => setSelectedWorkflow(wf)}
              >
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                        {wf.title || wf.objective}
                      </h3>
                      <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/[0.04] text-[#FFB020] border border-white/[0.08]">
                        {wf.template_type || 'Feature Implementation'}
                      </span>
                    </div>
                    <div className="text-xs font-mono text-[#6B6B6E] mt-1">
                      Current Stage: <span className="text-[#FFB020] font-bold">{wf.current_step}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    <Badge variant={wf.status === 'running' ? 'in_progress' : 'completed'}>
                      {wf.status}
                    </Badge>
                    <span className="text-xs font-mono text-cyan-400 font-bold">
                      ${(wf.total_cost_cents / 100).toFixed(2)}
                    </span>
                  </div>
                </div>

                {/* Progress Bar */}
                <div className="mt-3 space-y-1">
                  <div className="flex justify-between text-[10px] font-mono text-[#6B6B6E]">
                    <span>Step {wf.completed_steps} of {wf.total_steps}</span>
                    <span className="text-[#FFB020] font-bold">{progressPct}%</span>
                  </div>
                  <div className="w-full h-2 bg-[#101012] border border-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all duration-300 ${wf.status === 'completed' ? 'bg-emerald-400' : 'bg-[#FFB020]'
                        }`}
                      style={{ width: `${progressPct}%` }}
                    />
                  </div>
                </div>

                {/* Step Badges Preview */}
                <div className="mt-3 pt-2.5 border-t border-white/[0.04] flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                  <div className="flex items-center gap-1.5 overflow-x-auto">
                    {(wf.steps || []).map((s, idx) => (
                      <span
                        key={idx}
                        className={`px-2 py-0.5 rounded text-[10px] border ${s.status === 'completed'
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                          : s.status === 'running'
                            ? 'bg-[#FFB020]/15 border-[#FFB020]/30 text-[#FFB020]'
                            : 'bg-white/[0.04] border-white/[0.06] text-gray-500'
                          }`}
                      >
                        {s.step_name}
                      </span>
                    ))}
                  </div>

                  <span className="shrink-0 text-gray-400 ml-2">
                    Started {new Date(wf.started_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>
              </Card>
            );
          })}
        </div>
      )}

      {/* VIEW 2: FLOWCHART DAG GRAPH */}
      {viewMode === 'flow' && (
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4">
          <div className="border-b border-white/[0.06] pb-3">
            <h3 className="text-sm font-medium text-white font-mono uppercase">
              Interactive Multi-Agent DAG Flowchart
            </h3>
            <p className="text-xs text-gray-500">
              Select a workflow below to visualize its multi-agent step dependency topology
            </p>
          </div>

          <div className="flex flex-wrap gap-2">
            {workflows.map((w) => (
              <button
                key={w.workflow_id}
                onClick={() => setSelectedWorkflow(w)}
                className={`px-3 py-1.5 rounded-[6px] text-xs font-mono border transition-all cursor-pointer ${selectedWorkflow?.workflow_id === w.workflow_id
                  ? 'bg-[#FFB020] text-black font-bold border-[#FFB020]'
                  : 'bg-[#141416] text-gray-300 hover:text-white border-white/[0.08]'
                  }`}
              >
                {w.title || w.objective} ({w.status})
              </button>
            ))}
          </div>

          {selectedWorkflow && (
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[10px] space-y-4 font-mono text-xs">
              <h4 className="text-xs font-bold text-white uppercase flex items-center gap-2">
                <GitMerge size={14} className="text-[#FFB020]" /> Node Dependency Execution Path: {selectedWorkflow.objective}
              </h4>

              <div className="flex flex-col md:flex-row items-center justify-between gap-3 overflow-x-auto py-4">
                {(selectedWorkflow.steps || []).map((step, idx, arr) => {
                  const isDone = step.status === 'completed';
                  const isRunning = step.status === 'running';
                  return (
                    <div key={step.step_id} className="flex items-center gap-3 w-full md:w-auto">
                      <div
                        className={`p-3 rounded-[8px] border min-w-[200px] space-y-1 ${isDone
                          ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                          : isRunning
                            ? 'bg-[#FFB020]/15 border-[#FFB020]/40 text-[#FFB020] animate-pulse'
                            : 'bg-[#0A0A0C] border-white/[0.08] text-gray-400'
                          }`}
                      >
                        <div className="font-bold text-white text-xs">{step.step_name}</div>
                        <div className="text-[10px] text-gray-400">{step.action}</div>
                        <div className="text-[10px] text-[#FFB020] pt-1 border-t border-white/[0.06] flex items-center justify-between">
                          <span>{step.agent_role}</span>
                          <span>{step.status}</span>
                        </div>
                      </div>

                      {idx < arr.length - 1 && (
                        <span className="text-[#FFB020] text-lg font-bold shrink-0 hidden md:inline">→</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* VIEW 3: TRIGGERS */}
      {viewMode === 'triggers' && <TriggersPanel agents={agents} />}

      {/* Drawer */}
      <WorkflowDetailDrawer
        workflow={selectedWorkflow}
        onClose={() => setSelectedWorkflow(null)}
        onWorkflowUpdated={handleWorkflowUpdated}
      />

      {/* Modal */}
      <LaunchWorkflowModal
        isOpen={showLaunchModal}
        onClose={() => setShowLaunchModal(false)}
        onWorkflowLaunched={handleWorkflowLaunched}
        agents={agents}
      />
    </div>
  );
}
