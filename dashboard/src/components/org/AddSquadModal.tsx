import { useState } from 'react';
import { Layers, CheckCircle2, AlertCircle } from 'lucide-react';
import { Modal } from '@/components/common/Modal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import type { Squad, Department } from '@/types/organization';

interface AddSquadModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSquadAdded: (squad: Squad) => void;
  departments: Department[];
  agents: { id: string; name: string; role: string }[];
}

export function AddSquadModal({
  isOpen,
  onClose,
  onSquadAdded,
  departments,
  agents,
}: AddSquadModalProps) {
  const [name, setName] = useState('');
  const [departmentId, setDepartmentId] = useState('');
  const [leadAgentId, setLeadAgentId] = useState('');
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [description, setDescription] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [statusMsg, setStatusMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  if (!isOpen) return null;

  const handleClose = () => {
    setName('');
    setDepartmentId('');
    setLeadAgentId('');
    setSelectedAgentIds([]);
    setDescription('');
    setStatusMsg(null);
    onClose();
  };

  const handleToggleAgent = (agentId: string) => {
    setSelectedAgentIds((prev) =>
      prev.includes(agentId) ? prev.filter((id) => id !== agentId) : [...prev, agentId]
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setIsSubmitting(true);
    setStatusMsg(null);

    const selectedDept = departments.find((d) => d.id === departmentId);
    const selectedLead = agents.find((a) => a.id === leadAgentId || a.name === leadAgentId);

    try {
      const created = await apiClient.post<Squad>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/squads',
        {
          name: name.trim(),
          department_id: departmentId || departments[0]?.id || 'dept-eng',
          department_name: selectedDept?.name || 'Engineering',
          lead_agent_id: leadAgentId || agents[0]?.id || 'agent-atlas',
          lead_agent_name: selectedLead?.name || 'Atlas-01',
          lead_role: selectedLead?.role || 'Squad Lead',
          description: description.trim() || `Operational squad for ${name}`,
          agent_ids: selectedAgentIds.length ? selectedAgentIds : ['agent-atlas', 'agent-nova'],
          color: selectedDept?.color || '#FFB020',
          active_tasks_count: Math.floor(3 + Math.random() * 8),
          ast_coverage: 98,
          health_status: 'healthy',
        }
      );

      onSquadAdded(created);
      setStatusMsg({ type: 'success', text: `Squad '${created.name}' created successfully!` });
      setTimeout(() => {
        handleClose();
      }, 700);
    } catch (err: any) {
      setStatusMsg({ type: 'error', text: err?.detail || 'Failed to create squad' });
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} title="Create Operational Squad Cluster">
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

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Squad Name *
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Distributed Consensus Squad"
            className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            required
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Parent Department
            </label>
            <select
              value={departmentId}
              onChange={(e) => setDepartmentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="">-- Select Department --</option>
              {departments.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.code})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
              Squad Lead Agent
            </label>
            <select
              value={leadAgentId}
              onChange={(e) => setLeadAgentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
            >
              <option value="">-- Select Lead Agent --</option>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.role})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Assigned Squad Member Agents
          </label>
          <div className="p-3 bg-[#141416] border border-white/[0.12] rounded max-h-36 overflow-y-auto space-y-1.5">
            {agents.map((agent) => {
              const isSelected = selectedAgentIds.includes(agent.id) || selectedAgentIds.includes(agent.name);
              return (
                <label
                  key={agent.id}
                  className="flex items-center justify-between p-1.5 rounded hover:bg-white/[0.04] cursor-pointer text-xs"
                >
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => handleToggleAgent(agent.id)}
                      className="w-3.5 h-3.5 rounded border-gray-600 text-[#FFB020] focus:ring-0"
                    />
                    <span className="text-white font-medium">{agent.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500 font-mono">{agent.role}</span>
                </label>
              );
            })}
          </div>
        </div>

        <div>
          <label className="block text-[11px] font-mono text-[#A8A8AB] uppercase mb-1">
            Squad Description & Mission
          </label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={2}
            placeholder="Define squad objectives and delegation responsibilities..."
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
            icon={<Layers size={14} />}
          >
            {isSubmitting ? 'Creating...' : 'Create Squad'}
          </Button>
        </div>
      </form>
    </Modal>
  );
}
