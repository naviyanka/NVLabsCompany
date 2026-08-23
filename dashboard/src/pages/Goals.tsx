import { useState, useEffect } from 'react';
import { Target, Plus, TrendingUp, CheckCircle2 } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient } from '@/api/client';

interface GoalKR {
  id: string;
  title: string;
  progress: number;
  owner: string;
}

interface Goal {
  id: string;
  title: string;
  description: string;
  status: 'active' | 'completed' | 'paused';
  progress: number;
  target_date: string;
  key_results?: GoalKR[];
}

export function Goals() {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newTargetDate, setNewTargetDate] = useState('2025-12-31');

  useEffect(() => {
    async function loadGoals() {
      try {
        const res = await apiClient.get<{ items: Goal[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/goals'
        );
        if (res?.items) setGoals(res.items);
      } catch (err) {
        console.error('Failed to load goals', err);
      }
    }
    loadGoals();
  }, []);

  const handleCreateGoal = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    try {
      const created = await apiClient.post<Goal>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/goals',
        {
          title: newTitle,
          description: newDescription,
          status: 'active',
          progress: 0,
          target_date: newTargetDate,
        }
      );
      setGoals((prev) => [created, ...prev]);
      setShowCreateModal(false);
      setNewTitle('');
      setNewDescription('');
    } catch (err) {
      console.error('Goal creation failed', err);
    }
  };

  const handleIncrementProgress = async (goalId: string, current: number) => {
    const next = Math.min(100, current + 15);
    try {
      const updated = await apiClient.patch<Goal>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/goals/${goalId}`,
        {
          progress: next,
          status: next === 100 ? 'completed' : 'active',
        }
      );
      setGoals((prev) => prev.map((g) => (g.id === goalId ? updated : g)));
    } catch (err) {
      console.error('Failed to increment goal progress', err);
    }
  };

  const avgProgress = goals.length
    ? Math.round(goals.reduce((sum, g) => sum + g.progress, 0) / goals.length)
    : 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Target className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Strategic OKRs & Squad Directives
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Top-level organizational milestones mapped to autonomous agent pipelines
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowCreateModal(true)}
        >
          New Directive
        </Button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <StatCard
          label="Active Directives"
          value={goals.length}
          subValue="Strategic OKRs"
          change="Quarterly Cycle"
          changeType="neutral"
          icon={<Target className="w-4 h-4" />}
        />
        <StatCard
          label="Aggregate Progress"
          value={`${avgProgress}%`}
          subValue="Cross-squad average"
          change="+12% this cycle"
          changeType="positive"
          icon={<TrendingUp className="w-4 h-4" />}
        />
        <StatCard
          label="Completed Objectives"
          value={goals.filter((g) => g.status === 'completed').length}
          subValue="Delivered OKRs"
          change="On track"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4" />}
        />
      </div>

      {/* Goals Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {goals.map((goal) => (
          <Card key={goal.id}>
            <div className="flex items-start justify-between gap-2">
              <h3 className="text-sm font-medium text-[#F2F1EE]">{goal.title}</h3>
              <Badge variant={goal.status === 'completed' ? 'completed' : 'in_progress'}>
                {goal.status}
              </Badge>
            </div>

            <p className="text-xs text-[#9C9C9F] mt-2 leading-relaxed font-sans">
              {goal.description}
            </p>

            {/* Progress meter */}
            <div className="mt-4 space-y-1.5">
              <div className="flex items-center justify-between text-xs font-mono">
                <span className="text-[#6B6B6E]">Progress</span>
                <span className="text-[#FFB020] font-medium">{goal.progress}%</span>
              </div>
              <div className="w-full h-2 bg-[#101012] border border-white/[0.08] rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all duration-300 ${
                    goal.progress === 100 ? 'bg-[#22C55E]' : 'bg-[#FFB020]'
                  }`}
                  style={{ width: `${goal.progress}%` }}
                />
              </div>
            </div>

            <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between">
              <span className="text-[11px] font-mono text-[#6B6B6E]">
                Target: {goal.target_date}
              </span>
              {goal.progress < 100 && (
                <Button
                  variant="ghost"
                  size="xs"
                  onClick={() => handleIncrementProgress(goal.id, goal.progress)}
                >
                  + Progress Step
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>

      {/* Create Modal */}
      <Modal isOpen={showCreateModal} onClose={() => setShowCreateModal(false)} title="Define Strategic Goal">
        <form onSubmit={handleCreateGoal} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Goal / Objective Title
            </label>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="e.g. Sub-50ms Global Query Latency"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Target Milestone Date
            </label>
            <input
              type="date"
              value={newTargetDate}
              onChange={(e) => setNewTargetDate(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Description & Success Metric
            </label>
            <textarea
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              rows={3}
              placeholder="Outline quantifiable deliverables..."
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowCreateModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Establish Objective
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
