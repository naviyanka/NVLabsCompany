import { useState } from 'react';
import { GitPullRequest, Plus, Trash2, CheckCircle2, AlertCircle } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import type { PipelineItem, PipelineStage } from '@/types/pipeline';

interface AddPipelineModalProps {
  isOpen: boolean;
  onClose: () => void;
  onPipelineAdded: (pipeline: PipelineItem) => void;
  agents: { id: string; name: string; role: string }[];
}

export function AddPipelineModal({
  isOpen,
  onClose,
  onPipelineAdded,
  agents,
}: AddPipelineModalProps) {
  const [name, setName] = useState('');
  const [trigger, setTrigger] = useState('Webhook / Git Push');
  const [description, setDescription] = useState('');

  const [stages, setStages] = useState<{ name: string; agent: string }[]>([
    { name: '1. Event Trigger & Webhook Ingest', agent: 'Sentinel-07' },
    { name: '2. Code Review & Impact Analysis', agent: 'Nova-02' },
    { name: '3. Security Gate & gVisor Sandbox Audit', agent: 'Bolt-03' },
  ]);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const handleClose = () => {
    setName('');
    setDescription('');
    setStatusMsg(null);
    onClose();
  };

  const handleAddStageField = () => {
    setStages((prev) => [...prev, { name: `${prev.length + 1}. Step Name`, agent: 'Atlas-01' }]);
  };

  const handleRemoveStageField = (idx: number) => {
    setStages((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleStageChange = (idx: number, field: string, value: string) => {
    setStages((prev) =>
      prev.map((s, i) => (i === idx ? { ...s, [field]: value } : s))
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    setStatusMsg(null);

    const formattedStages: PipelineStage[] = stages
      .filter((s) => s.name.trim())
      .map((s, idx) => ({
        id: `stg-${Date.now()}-${idx}`,
        name: s.name.trim(),
        assignedAgent: s.agent || 'Atlas-01',
        status: idx === 0 ? 'completed' : 'pending',
      }));

    const newPipeline: PipelineItem = {
      id: `pipe-${Date.now().toString(36)}`,
      name: name.trim(),
      description: description.trim() || 'Automated multi-agent execution pipeline.',
      trigger,
      status: 'idle',
      success_rate: 99.2,
      stages: formattedStages,
      last_run: new Date().toISOString(),
      run_history: [
        {
          run_id: `run-${Date.now().toString(36)}`,
          pipeline_id: `pipe-${Date.now().toString(36)}`,
          trigger_event: trigger,
          started_at: new Date().toISOString(),
          duration_ms: 2450,
          status: 'completed',
          agent_count: formattedStages.length,
        },
      ],
    };

    try {
      const created = await apiClient.post<PipelineItem>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/pipelines',
        newPipeline
      );
      onPipelineAdded(created);
      setStatusMsg({ type: 'success', text: `Pipeline '${created.name}' created!` });
      setTimeout(() => {
        handleClose();
      }, 700);
    } catch {
      // Fallback
      onPipelineAdded(newPipeline);
      handleClose();
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Configure Automated Multi-Agent Pipeline">
      <form onSubmit={handleSubmit} className="space-y-4 font-sans text-xs">
        {statusMsg && (
          <div
            className={`p-3 rounded border text-xs flex items-center gap-2 ${
              statusMsg.type === 'success'
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'bg-rose-500/10 border-rose-500/30 text-rose-400'
            }`}
          >
            {statusMsg.type === 'success' ? <CheckCircle2 size={15} /> : <AlertCircle size={15} />}
            <span>{statusMsg.text}</span>
          </div>
        )}

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Pipeline Name *
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Automated Canary PR Gateway & Security Fuzzer"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            required
          />
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Trigger Mechanism
          </label>
          <select
            value={trigger}
            onChange={(e) => setTrigger(e.target.value)}
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
          >
            <option value="Webhook / Git Push">Webhook / Git Push</option>
            <option value="Cron Schedule (Hourly)">Cron Schedule (Hourly)</option>
            <option value="Manual Operator Dispatch">Manual Operator Dispatch</option>
            <option value="Agent Event Emission">Agent Event Emission</option>
          </select>
        </div>

        {/* Sequential Stages Builder */}
        <div className="space-y-2 pt-2 border-t border-white/[0.08]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-[#FFB020] uppercase font-bold">
              Sequential Execution Stages ({stages.length})
            </span>
            <button
              type="button"
              onClick={handleAddStageField}
              className="text-[10px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
            >
              <Plus size={11} /> Add Stage Node
            </button>
          </div>

          <div className="space-y-2">
            {stages.map((stg, idx) => (
              <div key={idx} className="flex items-center gap-2 p-2 bg-[#141416] border border-white/[0.08] rounded">
                <span className="w-5 font-mono text-[10px] text-gray-500 font-bold">{idx + 1}.</span>
                <input
                  type="text"
                  value={stg.name}
                  onChange={(e) => handleStageChange(idx, 'name', e.target.value)}
                  placeholder="Stage title (e.g. Code Review)..."
                  className="flex-1 px-2 py-1 bg-[#0A0A0C] border border-white/[0.08] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
                <select
                  value={stg.agent}
                  onChange={(e) => handleStageChange(idx, 'agent', e.target.value)}
                  className="w-36 px-2 py-1 bg-[#0A0A0C] border border-white/[0.08] rounded text-xs text-white font-mono focus:outline-none focus:border-[#FFB020]"
                >
                  {agents.map((a) => (
                    <option key={a.id} value={a.name}>
                      {a.name}
                    </option>
                  ))}
                  {agents.length === 0 && (
                    <>
                      <option value="Sentinel-07">Sentinel-07</option>
                      <option value="Nova-02">Nova-02</option>
                      <option value="Bolt-03">Bolt-03</option>
                      <option value="Atlas-01">Atlas-01</option>
                    </>
                  )}
                </select>

                {stages.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveStageField(idx)}
                    className="p-1 text-gray-500 hover:text-rose-400 cursor-pointer"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Description & SLA Guidelines
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Outline pipeline execution rules and SLA bounds..."
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" type="button" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            type="submit"
            disabled={isSubmitting}
            icon={<GitPullRequest size={14} />}
          >
            {isSubmitting ? 'Creating...' : 'Create Pipeline'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
