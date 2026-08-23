import { useState, useEffect } from 'react';
import {
  GitPullRequest,
  Play,
  Clock,
  Plus,
  ShieldCheck,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient } from '@/api/client';

interface PipelineStage {
  id: string;
  name: string;
  assignedAgent: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
}

interface Pipeline {
  id: string;
  name: string;
  status: 'idle' | 'running' | 'completed';
  success_rate: number;
  trigger: string;
  stages: PipelineStage[];
  last_run?: string;
}

export function Pipelines() {
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [selectedPipeline, setSelectedPipeline] = useState<Pipeline | null>(null);
  const [triggeringId, setTriggeringId] = useState<string | null>(null);

  // Create Modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newName, setNewName] = useState('');
  const [newTrigger, setNewTrigger] = useState('Webhook / Git Push');

  useEffect(() => {
    async function loadPipelines() {
      try {
        const res = await apiClient.get<{ items: Pipeline[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/pipelines'
        );
        if (res?.items && res.items.length > 0) {
          setPipelines(res.items);
          const first = res.items[0];
          if (first) setSelectedPipeline(first);
        }
      } catch (err) {
        console.error('Failed to load pipelines', err);
      }
    }
    loadPipelines();
  }, []);

  const handleTrigger = async (pipeId: string) => {
    setTriggeringId(pipeId);
    try {
      const res = await apiClient.post<{ message: string; pipeline: Pipeline }>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/pipelines/${pipeId}/trigger`
      );
      if (res?.pipeline) {
        setPipelines((prev) => prev.map((p) => (p.id === pipeId ? res.pipeline : p)));
        if (selectedPipeline?.id === pipeId) {
          setSelectedPipeline(res.pipeline);
        }
      }
    } catch (err) {
      console.error('Failed to run pipeline', err);
    } finally {
      setTriggeringId(null);
    }
  };

  const handleCreatePipeline = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    try {
      const created = await apiClient.post<Pipeline>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/pipelines',
        {
          name: newName,
          trigger: newTrigger,
          status: 'idle',
          success_rate: 98,
          stages: [
            { id: 'stg-1', name: 'Trigger Event', assignedAgent: 'Ops-Hook', status: 'completed' },
            { id: 'stg-2', name: 'Code Review & Lint', assignedAgent: 'Nova-02', status: 'pending' },
            { id: 'stg-3', name: 'Security Verification', assignedAgent: 'Shield-07', status: 'pending' },
          ],
        }
      );
      setPipelines((prev) => [...prev, created]);
      setSelectedPipeline(created);
      setShowCreateModal(false);
      setNewName('');
    } catch (err) {
      console.error('Pipeline creation failed', err);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <GitPullRequest className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Continuous Pipelines
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Automated multi-agent execution graphs, automated PR reviews, and CI gates
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowCreateModal(true)}
        >
          New Pipeline
        </Button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Active Pipelines"
          value={pipelines.length}
          subValue="Execution Graphs"
          change="All stages nominal"
          changeType="positive"
          icon={<GitPullRequest className="w-4 h-4" />}
        />
        <StatCard
          label="Aggregate Success Rate"
          value="98.5%"
          subValue="1,240 runs MTD"
          change="+0.8% vs last month"
          changeType="positive"
          icon={<ShieldCheck className="w-4 h-4" />}
        />
        <StatCard
          label="Mean Execution Time"
          value="1m 42s"
          subValue="Parallel agent dispatch"
          change="Optimal"
          changeType="neutral"
          icon={<Clock className="w-4 h-4" />}
        />
      </div>

      {/* Main Split: Pipelines List & Interactive Pipeline Execution Graph */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Pipelines List (5 cols) */}
        <div className="lg:col-span-5 space-y-3">
          <div className="text-xs font-mono font-medium text-[#6B6B6E] uppercase px-1">
            Configured Workflows
          </div>

          <div className="space-y-2.5">
            {pipelines.map((pipe) => {
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
                    <span className="text-[#22C55E]">{pipe.success_rate}% SLA</span>
                  </div>

                  <div className="mt-3 pt-3 border-t border-white/[0.04] flex items-center justify-between">
                    <span className="text-[10px] font-mono text-[#6B6B6E]">
                      {pipe.stages?.length || 3} Sequential Stages
                    </span>
                    <Button
                      variant="ghost"
                      size="xs"
                      icon={<Play className="w-3 h-3 text-[#FFB020]" />}
                      loading={triggeringId === pipe.id}
                      onClick={(e) => {
                        e.stopPropagation();
                        handleTrigger(pipe.id);
                      }}
                    >
                      Run Now
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Right Column: Selected Pipeline Stage Map & Execution History (7 cols) */}
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
                  <Button
                    variant="primary"
                    size="xs"
                    icon={<Play className="w-3 h-3" />}
                    loading={triggeringId === selectedPipeline.id}
                    onClick={() => handleTrigger(selectedPipeline.id)}
                  >
                    Execute Pipeline
                  </Button>
                </div>
              }
            >
              {/* Sequential Stage Diagram */}
              <div className="py-4 space-y-4">
                <div className="text-[10px] font-mono text-[#6B6B6E] uppercase tracking-wider">
                  Live Stage Graph
                </div>

                <div className="space-y-3">
                  {(selectedPipeline.stages || [
                    { id: '1', name: 'Trigger Event', assignedAgent: 'Ops-Hook', status: 'completed' },
                    { id: '2', name: 'Code Review & Lint', assignedAgent: 'Nova-02', status: selectedPipeline.status === 'running' ? 'running' : 'completed' },
                    { id: '3', name: 'Security Verification', assignedAgent: 'Shield-07', status: 'pending' },
                  ]).map((stage, idx, arr) => (
                    <div key={stage.id} className="relative">
                      <div className="p-3.5 bg-[#101012] border border-white/[0.06] rounded-[6px] flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className="w-6 h-6 rounded-[4px] bg-white/[0.04] border border-white/[0.08] flex items-center justify-center font-mono text-xs text-[#FFB020]">
                            {idx + 1}
                          </div>
                          <div>
                            <div className="text-xs font-medium text-[#F2F1EE]">{stage.name}</div>
                            <div className="text-[10px] font-mono text-[#6B6B6E]">
                              Assigned Agent: {stage.assignedAgent}
                            </div>
                          </div>
                        </div>

                        <Badge variant={stage.status as any}>{stage.status}</Badge>
                      </div>
                      {idx < arr.length - 1 && (
                        <div className="w-0.5 h-3 bg-white/[0.08] ml-6 my-0.5" />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </Card>
          ) : (
            <div className="p-12 text-center bg-[#141416] border border-white/[0.08] rounded-[10px] text-xs font-mono text-[#6B6B6E]">
              Select a pipeline to inspect stage execution graph.
            </div>
          )}
        </div>
      </div>

      {/* Create Pipeline Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title="Create Automated Pipeline"
      >
        <form onSubmit={handleCreatePipeline} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Pipeline Name
            </label>
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Threat Intelligence Ingest"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Trigger Mechanism
            </label>
            <select
              value={newTrigger}
              onChange={(e) => setNewTrigger(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Webhook / Git Push">Webhook / Git Push</option>
              <option value="Cron Schedule (Hourly)">Cron Schedule (Hourly)</option>
              <option value="Manual Dispatch">Manual Dispatch</option>
              <option value="Agent Event Emission">Agent Event Emission</option>
            </select>
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button
              variant="secondary"
              size="sm"
              type="button"
              onClick={() => setShowCreateModal(false)}
            >
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Create Pipeline
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
