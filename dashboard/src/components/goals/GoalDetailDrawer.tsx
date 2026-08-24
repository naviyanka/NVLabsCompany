import { useState } from 'react';
import {
  X,
  Target,
  CheckCircle2,
  Trash2,
  Plus,
  Sliders,
  Edit2,
} from 'lucide-react';
import type { GoalItem, KeyResult } from '@/types/goal';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';

interface GoalDetailDrawerProps {
  goal: GoalItem | null;
  onClose: () => void;
  onGoalUpdated: (updated: GoalItem) => void;
  onGoalDeleted: (goalId: string) => void;
}

export function GoalDetailDrawer({
  goal,
  onClose,
  onGoalUpdated,
  onGoalDeleted,
}: GoalDetailDrawerProps) {
  const [isUpdatingProgress, setIsUpdatingProgress] = useState(false);
  const [progressInput, setProgressInput] = useState(0);
  const [newKRTitle, setNewKRTitle] = useState('');
  const [isDeleting, setIsDeleting] = useState(false);

  if (!goal) return null;

  const keyResults = goal.key_results || [];

  const handleToggleKR = async (krId: string) => {
    const updatedKRs = keyResults.map((kr) => {
      if (kr.id === krId) {
        const nextStatus = kr.status === 'completed' ? 'in_progress' : 'completed';
        const nextVal = nextStatus === 'completed' ? kr.target_value : 0;
        return { ...kr, status: nextStatus as any, current_value: nextVal, progress: nextStatus === 'completed' ? 100 : 0 };
      }
      return kr;
    });

    const completedCount = updatedKRs.filter((k) => k.status === 'completed').length;
    const calcProgress = Math.round((completedCount / (updatedKRs.length || 1)) * 100);

    try {
      const updated = await apiClient.patch<GoalItem>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/goals/${goal.id}`,
        {
          key_results: updatedKRs,
          progress: calcProgress,
          status: calcProgress === 100 ? 'completed' : 'in_progress',
        }
      );
      onGoalUpdated(updated);
    } catch (err) {
      console.error('Failed to update KR', err);
    }
  };

  const handleAddKeyResult = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKRTitle.trim()) return;

    const newKR: KeyResult = {
      id: `kr-${Date.now()}`,
      title: newKRTitle.trim(),
      target_value: 100,
      current_value: 0,
      unit: '%',
      progress: 0,
      status: 'in_progress',
      owner_agent_name: goal.owner_agent_name || 'Atlas-01',
    };

    const updatedKRs = [...keyResults, newKR];

    try {
      const updated = await apiClient.patch<GoalItem>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/goals/${goal.id}`,
        { key_results: updatedKRs }
      );
      onGoalUpdated(updated);
      setNewKRTitle('');
    } catch (err) {
      console.error('Failed to add KR', err);
    }
  };

  const handleSaveProgress = async () => {
    try {
      const updated = await apiClient.patch<GoalItem>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/goals/${goal.id}`,
        {
          progress: progressInput,
          status: progressInput === 100 ? 'completed' : 'in_progress',
        }
      );
      onGoalUpdated(updated);
      setIsUpdatingProgress(false);
    } catch (err) {
      console.error('Failed to update goal progress', err);
    }
  };

  const handleDelete = async () => {
    if (!confirm(`Are you sure you want to delete objective "${goal.title}"?`)) return;
    setIsDeleting(true);
    try {
      await apiClient.delete(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/goals/${goal.id}`
      );
      onGoalDeleted(goal.id);
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
            <div className="p-2.5 bg-[#FFB020]/15 border border-[#FFB020]/30 rounded-[8px]">
              <Target className="w-5 h-5 text-[#FFB020]" />
            </div>
            <div>
              <h2 className="text-base font-medium text-white">{goal.title}</h2>
              <div className="flex items-center gap-2 text-xs font-mono text-[#6B6B6E] mt-0.5">
                <span>{goal.department_name || 'Engineering'}</span>
                <span>·</span>
                <span className="text-[#FFB020]">Owner: {goal.owner_agent_name || 'Atlas-01'}</span>
              </div>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 text-gray-400 hover:text-white rounded hover:bg-white/[0.06] transition-colors cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4 space-y-5 font-sans">
          {/* Progress Overview Card */}
          <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold font-mono text-white uppercase flex items-center gap-1.5">
                <Sliders size={14} className="text-[#FFB020]" /> Strategic Goal Progress
              </span>

              {!isUpdatingProgress ? (
                <button
                  onClick={() => {
                    setProgressInput(goal.progress);
                    setIsUpdatingProgress(true);
                  }}
                  className="text-xs font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                >
                  <Edit2 size={12} /> Adjust Progress
                </button>
              ) : (
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    min={0}
                    max={100}
                    value={progressInput}
                    onChange={(e) => setProgressInput(parseInt(e.target.value) || 0)}
                    className="w-16 px-2 py-0.5 bg-[#141416] border border-[#FFB020] rounded text-xs text-white font-mono"
                  />
                  <Button variant="primary" size="xs" onClick={handleSaveProgress}>
                    Save
                  </Button>
                </div>
              )}
            </div>

            <div className="flex items-center justify-between text-xs font-mono">
              <span className="text-gray-400">Target Date: {goal.target_date} ({goal.quarter || 'Q3 2026'})</span>
              <span className="text-[#FFB020] font-bold text-sm">{goal.progress}%</span>
            </div>

            <div className="w-full h-2.5 bg-white/[0.08] rounded-full overflow-hidden">
              <div
                className={`h-full transition-all ${
                  goal.progress === 100 ? 'bg-emerald-400' : 'bg-[#FFB020]'
                }`}
                style={{ width: `${Math.max(4, goal.progress)}%` }}
              />
            </div>
          </div>

          {/* Key Results Checklist */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold font-mono text-white uppercase flex items-center gap-1.5">
                <CheckCircle2 size={14} className="text-emerald-400" /> Key Results Breakdown ({keyResults.length})
              </span>
            </div>

            <div className="space-y-2 font-mono text-xs">
              {keyResults.map((kr) => {
                const isDone = kr.status === 'completed';
                return (
                  <div
                    key={kr.id}
                    onClick={() => handleToggleKR(kr.id)}
                    className={`p-3 rounded-[8px] border transition-all cursor-pointer flex items-center justify-between gap-3 ${
                      isDone
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                        : 'bg-[#141416] border-white/[0.08] text-white hover:border-white/[0.2]'
                    }`}
                  >
                    <div className="flex items-center gap-2.5">
                      <input
                        type="checkbox"
                        checked={isDone}
                        onChange={() => {}}
                        className="w-4 h-4 rounded border-gray-600 text-emerald-500 focus:ring-0 cursor-pointer"
                      />
                      <span className={isDone ? 'line-through opacity-80' : 'font-medium'}>
                        {kr.title}
                      </span>
                    </div>

                    <span className="text-[10px] text-gray-400 shrink-0">
                      {kr.target_value} {kr.unit}
                    </span>
                  </div>
                );
              })}
            </div>

            {/* Quick Add Key Result */}
            <form onSubmit={handleAddKeyResult} className="flex items-center gap-2 pt-2">
              <input
                type="text"
                value={newKRTitle}
                onChange={(e) => setNewKRTitle(e.target.value)}
                placeholder="Add new Key Result..."
                className="flex-1 px-3 py-1.5 bg-[#141416] border border-white/[0.1] rounded text-xs text-white focus:outline-none focus:border-[#FFB020]"
              />
              <Button variant="secondary" size="xs" type="submit" icon={<Plus size={12} />}>
                Add KR
              </Button>
            </form>
          </div>

          {/* Delete Action */}
          <div className="pt-4 border-t border-white/[0.08]">
            <Button
              variant="secondary"
              size="xs"
              onClick={handleDelete}
              disabled={isDeleting}
              icon={<Trash2 size={13} className="text-rose-400" />}
            >
              {isDeleting ? 'Deleting...' : 'Delete Objective'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
