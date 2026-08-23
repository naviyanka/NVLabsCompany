import { useState, useEffect } from 'react';
import { Plus, Clock, CheckCircle2, DollarSign, Layers } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient } from '@/api/client';

interface WorkflowItem {
  workflow_id: string;
  objective: string;
  status: 'running' | 'completed' | 'failed';
  current_step: string;
  total_steps: number;
  completed_steps: number;
  total_cost_cents: number;
  started_at: string;
}

export function Workflows() {
  const [workflows, setWorkflows] = useState<WorkflowItem[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [newObjective, setNewObjective] = useState('');

  useEffect(() => {
    async function loadWorkflows() {
      try {
        const res = await apiClient.get<{ items: WorkflowItem[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/workflows'
        );
        if (res?.items) setWorkflows(res.items);
      } catch (err) {
        console.error('Failed to load workflows', err);
      }
    }
    loadWorkflows();
  }, []);

  const handleCreateWorkflow = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newObjective.trim()) return;
    try {
      const created = await apiClient.post<WorkflowItem>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/workflows',
        {
          objective: newObjective,
          status: 'running',
          current_step: 'Decomposing task requirements',
          total_steps: 4,
          completed_steps: 1,
          total_cost_cents: 120,
        }
      );
      setWorkflows((prev) => [created, ...prev]);
      setShowModal(false);
      setNewObjective('');
    } catch (err) {
      console.error('Failed to launch workflow', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Layers className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Dynamic Multi-Agent Workflows
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Asynchronous DAG execution plans and delegation sequences
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowModal(true)}
        >
          Launch Workflow
        </Button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Active DAGs"
          value={workflows.filter((w) => w.status === 'running').length}
          subValue="In Flight"
          change="Parallel dispatch"
          changeType="positive"
          icon={<Layers className="w-4 h-4" />}
        />
        <StatCard
          label="Completed Executions"
          value={workflows.filter((w) => w.status === 'completed').length}
          subValue="Total Finished"
          change="100% SLA compliance"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
        <StatCard
          label="Total Execution Spend"
          value={`$${(workflows.reduce((s, w) => s + w.total_cost_cents, 0) / 100).toFixed(2)}`}
          subValue="Token Spend"
          change="Cost-efficient"
          changeType="neutral"
          icon={<DollarSign className="w-4 h-4" />}
        />
      </div>

      {/* Workflows List */}
      <div className="space-y-3">
        {workflows.map((wf) => {
          const progressPct = Math.round((wf.completed_steps / wf.total_steps) * 100);
          return (
            <Card key={wf.workflow_id}>
              <div className="flex items-start justify-between gap-3 mb-2">
                <div>
                  <h3 className="text-sm font-medium text-[#F2F1EE]">{wf.objective}</h3>
                  <div className="text-xs font-mono text-[#6B6B6E] mt-0.5">
                    Current stage: <span className="text-[#FFB020]">{wf.current_step}</span>
                  </div>
                </div>
                <Badge variant={wf.status === 'running' ? 'in_progress' : 'completed'}>
                  {wf.status}
                </Badge>
              </div>

              {/* Progress Bar */}
              <div className="mt-3 space-y-1">
                <div className="flex justify-between text-[10px] font-mono text-[#6B6B6E]">
                  <span>Step {wf.completed_steps} of {wf.total_steps}</span>
                  <span>{progressPct}%</span>
                </div>
                <div className="w-full h-1.5 bg-[#101012] border border-white/[0.08] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[#FFB020] transition-all duration-300"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              </div>

              <div className="mt-3 pt-2.5 border-t border-white/[0.04] flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                <span className="flex items-center gap-1">
                  <Clock size={11} /> Started {new Date(wf.started_at).toLocaleTimeString()}
                </span>
                <span className="text-[#F2F1EE]">Cost: ${(wf.total_cost_cents / 100).toFixed(2)}</span>
              </div>
            </Card>
          );
        })}
      </div>

      {/* Launch Modal */}
      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title="Launch Dynamic Multi-Agent Workflow">
        <form onSubmit={handleCreateWorkflow} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Workflow Objective
            </label>
            <input
              type="text"
              value={newObjective}
              onChange={(e) => setNewObjective(e.target.value)}
              placeholder="e.g. End-to-End Penetration Test & Remediation PR"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Dispatch Workflow
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
