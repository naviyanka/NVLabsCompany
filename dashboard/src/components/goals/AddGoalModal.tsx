import { useState } from 'react';
import { Target, Plus, Trash2, CheckCircle2, AlertCircle } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import type { GoalItem, KeyResult } from '@/types/goal';

interface AddGoalModalProps {
  isOpen: boolean;
  onClose: () => void;
  onGoalAdded: (goal: GoalItem) => void;
  agents: { id: string; name: string; role: string }[];
}

export function AddGoalModal({
  isOpen,
  onClose,
  onGoalAdded,
  agents,
}: AddGoalModalProps) {
  const [title, setTitle] = useState('');
  const [department, setDepartment] = useState('Engineering & Core Tech');
  const [ownerAgentId, setOwnerAgentId] = useState('');
  const [targetDate, setTargetDate] = useState('2026-12-31');
  const [quarter, setQuarter] = useState('Q3 2026');
  const [description, setDescription] = useState('');

  // Key Results
  const [keyResults, setKeyResults] = useState<{ title: string; target: string; unit: string }[]>([
    { title: 'Reduce API p99 query latency', target: '50', unit: 'ms' },
  ]);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const handleClose = () => {
    setTitle('');
    setDescription('');
    setStatusMsg(null);
    onClose();
  };

  const handleAddKRField = () => {
    setKeyResults((prev) => [...prev, { title: '', target: '100', unit: '%' }]);
  };

  const handleRemoveKRField = (idx: number) => {
    setKeyResults((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleKRChange = (idx: number, field: string, value: string) => {
    setKeyResults((prev) =>
      prev.map((kr, i) => (i === idx ? { ...kr, [field]: value } : kr))
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    setIsSubmitting(true);
    setStatusMsg(null);

    const selectedAgent = agents.find((a) => a.id === ownerAgentId || a.name === ownerAgentId);

    const formattedKRs: KeyResult[] = keyResults
      .filter((kr) => kr.title.trim())
      .map((kr, idx) => ({
        id: `kr-${Date.now()}-${idx}`,
        title: kr.title.trim(),
        target_value: parseFloat(kr.target) || 100,
        current_value: 0,
        unit: kr.unit || '%',
        progress: 0,
        status: 'not_started',
        owner_agent_name: selectedAgent?.name || 'Atlas-01',
      }));

    try {
      const created = await apiClient.post<GoalItem>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/goals',
        {
          title: title.trim(),
          description: description.trim() || 'Strategic operational directive.',
          department_name: department,
          owner_agent_id: ownerAgentId || agents[0]?.id || 'agent-atlas',
          owner_agent_name: selectedAgent?.name || 'Atlas-01',
          status: 'in_progress',
          progress: 0,
          target_date: targetDate,
          quarter,
          key_results: formattedKRs,
        }
      );

      onGoalAdded(created);
      setStatusMsg({ type: 'success', text: `Directive '${created.title}' established!` });
      setTimeout(() => {
        handleClose();
      }, 700);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err?.detail || 'Failed to create goal' });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Establish Strategic Goal / OKR Directive">
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
            Goal / Objective Title *
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Achieve Sub-50ms Global Query Latency"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Department
            </label>
            <select
              value={department}
              onChange={(e) => setDepartment(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Engineering & Core Tech">Engineering & Core Tech</option>
              <option value="AI Research & Reasoning">AI Research & Reasoning</option>
              <option value="Infrastructure & Security">Infrastructure & Security</option>
              <option value="Executive Operations">Executive Operations</option>
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Owner Agent Lead
            </label>
            <select
              value={ownerAgentId}
              onChange={(e) => setOwnerAgentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="">-- Select Owner Agent --</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.role})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Target Milestone Date
            </label>
            <input
              type="date"
              value={targetDate}
              onChange={(e) => setTargetDate(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Target Quarter
            </label>
            <select
              value={quarter}
              onChange={(e) => setQuarter(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Q3 2026">Q3 2026</option>
              <option value="Q4 2026">Q4 2026</option>
              <option value="Q1 2027">Q1 2027</option>
            </select>
          </div>
        </div>

        {/* Key Results Builder */}
        <div className="space-y-2 pt-2 border-t border-white/[0.08]">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-[#FFB020] uppercase font-bold">
              Nested Key Results (KRs)
            </span>
            <button
              type="button"
              onClick={handleAddKRField}
              className="text-[10px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
            >
              <Plus size={11} /> Add Key Result
            </button>
          </div>

          <div className="space-y-2">
            {keyResults.map((kr, idx) => (
              <div key={idx} className="flex items-center gap-2 p-2 bg-[#141416] border border-white/[0.08] rounded">
                <input
                  type="text"
                  value={kr.title}
                  onChange={(e) => handleKRChange(idx, 'title', e.target.value)}
                  placeholder="Key result title (e.g. Zero 500 errors)..."
                  className="flex-1 px-2 py-1 bg-[#0A0A0C] border border-white/[0.08] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
                <input
                  type="text"
                  value={kr.target}
                  onChange={(e) => handleKRChange(idx, 'target', e.target.value)}
                  placeholder="Target"
                  className="w-16 px-2 py-1 bg-[#0A0A0C] border border-white/[0.08] rounded text-xs text-white font-mono"
                />
                <input
                  type="text"
                  value={kr.unit}
                  onChange={(e) => handleKRChange(idx, 'unit', e.target.value)}
                  placeholder="Unit"
                  className="w-14 px-2 py-1 bg-[#0A0A0C] border border-white/[0.08] rounded text-xs text-white font-mono"
                />
                {keyResults.length > 1 && (
                  <button
                    type="button"
                    onClick={() => handleRemoveKRField(idx)}
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
            Description & Quantifiable Metrics
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Outline success metrics and scope boundaries..."
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
            icon={<Target size={14} />}
          >
            {isSubmitting ? 'Establishing...' : 'Establish Objective'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
