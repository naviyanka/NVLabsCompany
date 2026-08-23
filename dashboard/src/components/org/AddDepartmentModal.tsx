import { useState } from 'react';
import { Building2, DollarSign, CheckCircle2, AlertCircle } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import type { Department } from '@/types/organization';

interface AddDepartmentModalProps {
  isOpen: boolean;
  onClose: () => void;
  onDepartmentAdded: (dept: Department) => void;
  agents: { id: string; name: string; role: string }[];
}

export function AddDepartmentModal({
  isOpen,
  onClose,
  onDepartmentAdded,
  agents,
}: AddDepartmentModalProps) {
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [headAgentId, setHeadAgentId] = useState('');
  const [budgetUsd, setBudgetUsd] = useState('25000');
  const [description, setDescription] = useState('');
  const [color, setColor] = useState('#FFB020');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const handleClose = () => {
    setName('');
    setCode('');
    setHeadAgentId('');
    setDescription('');
    setStatusMsg(null);
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    setStatusMsg(null);

    const selectedAgent = agents.find((a) => a.id === headAgentId || a.name === headAgentId);

    try {
      const created = await apiClient.post<Department>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/departments',
        {
          name: name.trim(),
          code: code.trim().toUpperCase() || name.substring(0, 3).toUpperCase(),
          head_agent_id: headAgentId || agents[0]?.id || 'agent-atlas',
          head_agent_name: selectedAgent?.name || 'Atlas-01',
          head_agent_role: selectedAgent?.role || 'Staff Architect',
          description: description.trim() || `Department envelope for ${name}`,
          monthly_budget_cents: (parseFloat(budgetUsd) || 25000) * 100,
          color,
        }
      );

      onDepartmentAdded(created);
      setStatusMsg({ type: 'success', text: `Department '${created.name}' created!` });
      setTimeout(() => {
        handleClose();
      }, 700);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err?.detail || 'Failed to create department' });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Create Organizational Department">
      <form onSubmit={handleSubmit} className="space-y-4 font-sans">
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

        <div className="grid grid-cols-3 gap-3">
          <div className="col-span-2">
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Department Name *
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (!code) setCode(e.target.value.substring(0, 3).toUpperCase());
              }}
              placeholder="e.g. Cognitive AI & Research"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Code (Prefix)
            </label>
            <input
              type="text"
              value={code}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
              placeholder="e.g. COG"
              maxLength={4}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white font-mono uppercase focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Department Head Agent
            </label>
            <select
              value={headAgentId}
              onChange={(e) => setHeadAgentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="">-- Select Head Agent --</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.role})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Monthly Budget Allocation ($ USD)
            </label>
            <div className="relative">
              <DollarSign size={14} className="text-gray-400 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="number"
                value={budgetUsd}
                onChange={(e) => setBudgetUsd(e.target.value)}
                placeholder="25000"
                className="w-full pl-8 pr-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white font-mono focus:outline-none focus:border-[#FFB020]"
              />
            </div>
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Department Color Identifier
          </label>
          <div className="flex items-center gap-2">
            {['#FFB020', '#38BDF8', '#22C55E', '#A855F7', '#F43F5E', '#EC4899', '#6366F1'].map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => setColor(c)}
                className={`w-6 h-6 rounded-full border-2 transition-all cursor-pointer ${
                  color === c ? 'border-white scale-110 shadow' : 'border-transparent opacity-70 hover:opacity-100'
                }`}
                style={{ backgroundColor: c }}
              />
            ))}
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Description & Scope
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            placeholder="Define department operational responsibilities and delegation bounds..."
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
            icon={<Building2 size={14} />}
          >
            {isSubmitting ? 'Creating...' : 'Create Department'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
