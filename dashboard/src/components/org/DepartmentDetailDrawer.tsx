import { useState } from 'react';
import {
  X,
  Users,
  DollarSign,
  Layers,
  Trash2,
  Edit2,
  ArrowUpRight,
} from 'lucide-react';
import type { Department, Squad } from '@/types/organization';
import type { Agent } from '@/types/agent';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { useNavigate } from 'react-router-dom';

interface DepartmentDetailDrawerProps {
  department: Department | null;
  squads: Squad[];
  agents: Agent[];
  onClose: () => void;
  onDepartmentUpdated: (updated: Department) => void;
  onDepartmentDeleted: (deptId: string) => void;
}

export function DepartmentDetailDrawer({
  department,
  squads,
  agents,
  onClose,
  onDepartmentUpdated,
  onDepartmentDeleted,
}: DepartmentDetailDrawerProps) {
  const navigate = useNavigate();
  const [isEditingBudget, setIsEditingBudget] = useState(false);
  const [budgetUsdInput, setBudgetUsdInput] = useState('');
  const [isSavingBudget, setIsSavingBudget] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  if (!department) return null;

  const deptSquads = squads.filter(
    (s) => s.department_id === department.id || s.department_name === department.name
  );
  const deptAgents = agents.filter(
    (a) => a.department_id === department.id || a.role.toLowerCase().includes(department.code.toLowerCase())
  );

  const budgetUsd = department.monthly_budget_cents / 100;
  const spentUsd = department.spent_cents / 100;
  const spendPct = Math.min(100, Math.round((spentUsd / (budgetUsd || 1)) * 100));

  const handleSaveBudget = async () => {
    const parsed = parseFloat(budgetUsdInput);
    if (isNaN(parsed) || parsed < 0) return;
    setIsSavingBudget(true);

    try {
      const updated = await apiClient.patch<Department>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/departments/${department.id}`,
        { monthly_budget_cents: parsed * 100 }
      );
      onDepartmentUpdated(updated);
      setIsEditingBudget(false);
    } catch (err: any) {
      console.error('Failed to update budget', err);
    } finally {
      setIsSavingBudget(false);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Are you sure you want to delete department "${department.name}"?`)) return;
    setIsDeleting(true);
    try {
      await apiClient.delete(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/departments/${department.id}`
      );
      onDepartmentDeleted(department.id);
      onClose();
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/60 backdrop-blur-sm flex justify-end">
      <div className="w-full max-w-xl bg-[#0A0A0C] border-l border-white/[0.1] h-full flex flex-col shadow-2xl">
        {/* Header */}
        <div className="p-4 border-b border-white/[0.08] flex items-center justify-between bg-[#101012]">
          <div className="flex items-center gap-3">
            <div
              className="p-2.5 rounded-[8px] border font-mono font-bold text-sm"
              style={{
                backgroundColor: `${department.color || '#FFB020'}20`,
                borderColor: `${department.color || '#FFB020'}40`,
                color: department.color || '#FFB020',
              }}
            >
              {department.code}
            </div>
            <div>
              <h2 className="text-base font-medium text-white">{department.name}</h2>
              <p className="text-xs text-[#6B6B6E] font-mono mt-0.5">
                Head: <span className="text-white">{department.head_agent_name}</span> ({department.head_agent_role})
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4 font-sans">
          {/* Description */}
          <div className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-1">
            <span className="text-[10px] font-mono uppercase text-gray-400">Department Description</span>
            <p className="text-xs text-gray-300 leading-relaxed">{department.description}</p>
          </div>

          {/* Budget Allocation Card */}
          <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold font-mono text-white uppercase flex items-center gap-1.5">
                <DollarSign size={14} className="text-[#FFB020]" /> Monthly Budget Allocation
              </span>

              {!isEditingBudget ? (
                <button
                  onClick={() => {
                    setBudgetUsdInput(budgetUsd.toString());
                    setIsEditingBudget(true);
                  }}
                  className="text-xs font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                >
                  <Edit2 size={12} /> Edit Budget
                </button>
              ) : (
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    value={budgetUsdInput}
                    onChange={(e) => setBudgetUsdInput(e.target.value)}
                    className="w-24 px-2 py-0.5 bg-[#141416] border border-[#FFB020] rounded text-xs text-white font-mono"
                  />
                  <Button variant="primary" size="xs" onClick={handleSaveBudget} disabled={isSavingBudget}>
                    {isSavingBudget ? 'Saving...' : 'Save'}
                  </Button>
                </div>
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div>
                <span className="text-gray-500 block text-[10px]">MONTHLY BUDGET</span>
                <span className="text-white font-bold text-sm">${budgetUsd.toLocaleString()} USD</span>
              </div>
              <div>
                <span className="text-gray-500 block text-[10px]">SPENT THIS MONTH</span>
                <span className="text-[#FFB020] font-bold text-sm">${spentUsd.toLocaleString()} USD ({spendPct}%)</span>
              </div>
            </div>

            {/* Progress bar */}
            <div className="w-full h-2 bg-white/[0.08] rounded-full overflow-hidden">
              <div
                className="h-full bg-[#FFB020] transition-all"
                style={{ width: `${Math.max(5, spendPct)}%` }}
              />
            </div>
          </div>

          {/* Squad Clusters in Dept */}
          <div className="space-y-2">
            <div className="text-xs font-bold font-mono text-white uppercase flex items-center gap-1.5">
              <Layers size={13} className="text-cyan-400" /> Operational Squad Clusters ({deptSquads.length})
            </div>

            {deptSquads.map((squad) => (
              <div key={squad.id} className="p-3 bg-[#141416] border border-white/[0.06] rounded-[8px] space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-white">{squad.name}</span>
                  <span className="px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 text-[9px] font-mono">
                    HEALTHY
                  </span>
                </div>
                <div className="text-[11px] text-gray-400 font-mono">
                  Lead: <span className="text-white">{squad.lead_agent_name}</span> ({squad.lead_role})
                </div>
              </div>
            ))}
          </div>

          {/* Member Agents */}
          <div className="space-y-2">
            <div className="text-xs font-bold font-mono text-white uppercase flex items-center gap-1.5">
              <Users size={13} className="text-purple-400" /> Assigned Squad Agents ({deptAgents.length || agents.length})
            </div>

            <div className="space-y-1.5">
              {(deptAgents.length ? deptAgents : agents).map((agent) => (
                <div
                  key={agent.id}
                  onClick={() => navigate(`/agents/${agent.id}`)}
                  className="p-2.5 bg-[#141416] border border-white/[0.06] hover:border-white/[0.2] rounded-[8px] flex items-center justify-between cursor-pointer group transition-colors"
                >
                  <div className="flex items-center gap-2.5">
                    <div className="w-7 h-7 rounded bg-white/[0.04] border border-white/[0.1] flex items-center justify-center font-mono text-xs text-[#FFB020]">
                      {agent.name.substring(0, 2).toUpperCase()}
                    </div>
                    <div>
                      <div className="text-xs font-medium text-white group-hover:text-[#FFB020] transition-colors">
                        {agent.name}
                      </div>
                      <div className="text-[10px] text-gray-500 font-mono">{agent.role}</div>
                    </div>
                  </div>

                  <span className="text-[10px] font-mono text-[#FFB020] group-hover:underline flex items-center gap-1">
                    Dossier <ArrowUpRight size={10} />
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Delete Department */}
          <div className="pt-4 border-t border-white/[0.08]">
            <Button
              variant="secondary"
              size="xs"
              onClick={handleDelete}
              disabled={isDeleting}
              icon={<Trash2 size={13} className="text-rose-400" />}
            >
              {isDeleting ? 'Deleting...' : 'Delete Department'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
