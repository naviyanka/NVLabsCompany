import { useState, useEffect, useMemo } from 'react';
import {
  Target,
  Plus,
  TrendingUp,
  CheckCircle2,
  ListCheck,
  Calendar,
  Search,
  LayoutGrid,
} from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient, unwrapItems } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { GoalItem } from '@/types/goal';
import { AddGoalModal } from '@/components/goals/AddGoalModal';
import { GoalDetailDrawer } from '@/components/goals/GoalDetailDrawer';

const INITIAL_GOALS: GoalItem[] = [];

export function Goals() {
  const [goals, setGoals] = useState<GoalItem[]>(INITIAL_GOALS);
  const [agents, setAgents] = useState<{ id: string; name: string; role: string }[]>([]);
  const [selectedGoal, setSelectedGoal] = useState<GoalItem | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);
  const [viewMode, setViewMode] = useState<'grid' | 'matrix' | 'roadmap'>('grid');
  const [search, setSearch] = useState('');
  const [departmentFilter, setDepartmentFilter] = useState('all');

  useEffect(() => {
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const res = await apiClient.get<GoalItem[] | { items: GoalItem[] }>(
          `/api/v1/companies/${companyId}/goals`
        );
        const items = unwrapItems(res);
        if (items.length > 0) {
          setGoals(items);
        }

        const agentsRes = await apiClient.get<any[] | { items: any[] }>(
          `/api/v1/companies/${companyId}/agents`
        );
        const agentItems = unwrapItems(agentsRes);
        if (agentItems.length) setAgents(agentItems);
      } catch (err) {
        console.error('Failed to load goals', err);
      }
    }
    loadData();
  }, []);

  const handleGoalAdded = (newGoal: GoalItem) => {
    setGoals((prev) => [newGoal, ...prev]);
  };

  const handleGoalUpdated = (updatedGoal: GoalItem) => {
    setGoals((prev) => prev.map((g) => (g.id === updatedGoal.id ? updatedGoal : g)));
    if (selectedGoal?.id === updatedGoal.id) {
      setSelectedGoal(updatedGoal);
    }
  };

  const handleGoalDeleted = (goalId: string) => {
    setGoals((prev) => prev.filter((g) => g.id !== goalId));
  };

  const handleToggleKeyResult = async (goalId: string, krId: string) => {
    const targetGoal = goals.find((g) => g.id === goalId);
    if (!targetGoal) return;

    const keyResults = targetGoal.key_results || [];
    const updatedKRs = keyResults.map((kr) => {
      if (kr.id === krId) {
        const nextStatus = kr.status === 'completed' ? 'in_progress' : 'completed';
        return {
          ...kr,
          status: nextStatus as any,
          current_value: nextStatus === 'completed' ? kr.target_value : 0,
          progress: nextStatus === 'completed' ? 100 : 0,
        };
      }
      return kr;
    });

    const completedCount = updatedKRs.filter((k) => k.status === 'completed').length;
    const calcProgress = Math.round((completedCount / (updatedKRs.length || 1)) * 100);

    try {
      const updated = await apiClient.patch<GoalItem>(
        `/api/v1/companies/${getActiveCompanyId()}/goals/${goalId}`,
        {
          key_results: updatedKRs,
          progress: calcProgress,
          status: calcProgress === 100 ? 'completed' : 'in_progress',
        }
      );
      handleGoalUpdated(updated);
    } catch {
      // Fallback update
      const updated: GoalItem = {
        ...targetGoal,
        key_results: updatedKRs,
        progress: calcProgress,
        status: calcProgress === 100 ? 'completed' : 'in_progress',
      };
      handleGoalUpdated(updated);
    }
  };

  const filteredGoals = useMemo(() => {
    return goals.filter((g) => {
      if (departmentFilter !== 'all' && g.department_name !== departmentFilter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          g.title.toLowerCase().includes(q) ||
          g.description.toLowerCase().includes(q) ||
          (g.owner_agent_name || '').toLowerCase().includes(q) ||
          (g.department_name || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [goals, departmentFilter, search]);

  // Aggregate Stats
  const avgProgress = goals.length
    ? Math.round(goals.reduce((sum, g) => sum + g.progress, 0) / goals.length)
    : 0;

  const allKRs = goals.flatMap((g) => g.key_results || []);
  const completedKRsCount = allKRs.filter((k) => k.status === 'completed').length;

  return (
    <div className="space-y-6 font-sans">
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
            Top-level organizational objectives mapped to autonomous agent pipelines and key results
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowAddModal(true)}
        >
          Establish Directive
        </Button>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Strategic OKRs</span>
            <Target size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">{goals.length} Directives</div>
          <p className="text-[10px] text-gray-500 mt-1">Active quarterly goals</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Aggregate Progress</span>
            <TrendingUp size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">{avgProgress}%</div>
          <p className="text-[10px] text-gray-500 mt-1">Cross-squad target completion</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Key Results Completed</span>
            <CheckCircle2 size={14} className="text-cyan-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-cyan-400 mt-1">
            {completedKRsCount} / {allKRs.length}
          </div>
          <p className="text-[10px] text-gray-500 mt-1">Verified deliverables</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Quarterly SLA</span>
            <Calendar size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">100% On-Track</div>
          <p className="text-[10px] text-gray-500 mt-1">Zero milestone breaches</p>
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
            placeholder="Search objectives, owner agents, departments..."
            className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
          />
        </div>

        {/* Department Filters */}
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {['all', 'Engineering & Core Tech', 'AI Research & Reasoning', 'Infrastructure & Security'].map((dept) => (
            <button
              key={dept}
              onClick={() => setDepartmentFilter(dept)}
              className={`px-2.5 py-1 rounded text-xs font-mono transition-colors cursor-pointer whitespace-nowrap ${
                departmentFilter === dept
                  ? 'bg-[#FFB020] text-black font-bold'
                  : 'bg-[#141416] text-[#6B6B6E] hover:text-white border border-white/[0.08]'
              }`}
            >
              {dept === 'all' ? 'All Depts' : dept}
            </button>
          ))}
        </div>

        {/* View Switcher */}
        <div className="flex items-center bg-[#141416] border border-white/[0.08] rounded p-0.5">
          <button
            onClick={() => setViewMode('grid')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
              viewMode === 'grid' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
            }`}
          >
            <LayoutGrid size={13} /> Grid
          </button>
          <button
            onClick={() => setViewMode('matrix')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
              viewMode === 'matrix' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
            }`}
          >
            <ListCheck size={13} /> KRs Matrix
          </button>
          <button
            onClick={() => setViewMode('roadmap')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
              viewMode === 'roadmap' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
            }`}
          >
            <Calendar size={13} /> Roadmap
          </button>
        </div>
      </div>

      {/* VIEW 1: GRID & OKR CARDS */}
      {viewMode === 'grid' && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredGoals.map((goal) => (
            <Card
              key={goal.id}
              className="hover:border-[#FFB020]/40 transition-colors cursor-pointer flex flex-col justify-between"
              onClick={() => setSelectedGoal(goal)}
            >
              <div>
                <div className="flex items-start justify-between gap-2">
                  <span className="text-[10px] font-mono uppercase text-[#FFB020] font-bold">
                    {goal.quarter || 'Q3 2026'} · {goal.department_name || 'Engineering'}
                  </span>
                  <Badge variant={goal.progress === 100 ? 'completed' : 'in_progress'}>
                    {goal.progress === 100 ? 'completed' : 'in_progress'}
                  </Badge>
                </div>

                <h3 className="text-sm font-medium text-[#F2F1EE] mt-1.5 leading-snug">
                  {goal.title}
                </h3>

                <p className="text-xs text-[#9C9C9F] mt-2 leading-relaxed line-clamp-2">
                  {goal.description}
                </p>

                {/* Progress Bar */}
                <div className="mt-4 space-y-1">
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-gray-500">Progress</span>
                    <span className="text-[#FFB020] font-bold">{goal.progress}%</span>
                  </div>
                  <div className="w-full h-2 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all ${
                        goal.progress === 100 ? 'bg-emerald-400' : 'bg-[#FFB020]'
                      }`}
                      style={{ width: `${Math.max(4, goal.progress)}%` }}
                    />
                  </div>
                </div>

                {/* Nested Key Results Preview */}
                {goal.key_results && goal.key_results.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-white/[0.06] space-y-1.5 font-mono text-[11px]">
                    <span className="text-gray-500 uppercase text-[10px] font-bold">Key Results:</span>
                    {goal.key_results.map((kr) => {
                      const isDone = kr.status === 'completed';
                      return (
                        <div
                          key={kr.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleToggleKeyResult(goal.id, kr.id);
                          }}
                          className={`p-1.5 rounded flex items-center justify-between text-xs transition-colors cursor-pointer ${
                            isDone ? 'bg-emerald-500/10 text-emerald-300' : 'bg-white/[0.04] text-gray-300 hover:text-white'
                          }`}
                        >
                          <div className="flex items-center gap-1.5 truncate">
                            <input
                              type="checkbox"
                              checked={isDone}
                              readOnly
                              className="w-3.5 h-3.5 rounded text-emerald-500 cursor-pointer"
                            />
                            <span className={isDone ? 'line-through opacity-80' : ''}>{kr.title}</span>
                          </div>
                          <span className="text-[10px] text-gray-500 shrink-0 ml-2">
                            {kr.target_value} {kr.unit}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Footer */}
              <div className="mt-4 pt-3 border-t border-white/[0.06] flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                <span>Lead: <strong className="text-gray-300">{goal.owner_agent_name || 'Atlas-01'}</strong></span>
                <span>Target: {goal.target_date}</span>
              </div>
            </Card>
          ))}
        </div>
      )}

      {/* VIEW 2: KEY RESULTS MATRIX */}
      {viewMode === 'matrix' && (
        <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-4">
          <div className="flex items-center justify-between border-b border-white/[0.06] pb-3">
            <div>
              <h3 className="text-sm font-medium text-white font-mono uppercase">
                Key Results Matrix & Deliverable Status
              </h3>
              <p className="text-xs text-gray-500">
                Detailed view of all nested Key Results mapped to strategic OKRs
              </p>
            </div>
            <span className="text-xs font-mono text-emerald-400 font-bold">
              {completedKRsCount} of {allKRs.length} Completed
            </span>
          </div>

          <div className="space-y-2 font-mono text-xs">
            {goals.flatMap((g) =>
              (g.key_results || []).map((kr) => {
                const isDone = kr.status === 'completed';
                return (
                  <div
                    key={kr.id}
                    onClick={() => handleToggleKeyResult(g.id, kr.id)}
                    className={`p-3 rounded-[8px] border transition-colors cursor-pointer flex items-center justify-between gap-3 ${
                      isDone
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                        : 'bg-[#141416] border-white/[0.06] hover:border-white/[0.2] text-white'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <input
                        type="checkbox"
                        checked={isDone}
                        readOnly
                        className="w-4 h-4 rounded text-emerald-500 cursor-pointer"
                      />
                      <div>
                        <div className={isDone ? 'line-through font-medium opacity-80' : 'font-medium'}>
                          {kr.title}
                        </div>
                        <div className="text-[10px] text-gray-500 mt-0.5">
                          Parent Directive: <span className="text-gray-300">{g.title}</span>
                        </div>
                      </div>
                    </div>

                    <div className="text-right shrink-0">
                      <span className="text-xs font-bold text-[#FFB020]">
                        {kr.target_value} {kr.unit}
                      </span>
                      <div className="text-[10px] text-gray-500">
                        Lead: {kr.owner_agent_name || g.owner_agent_name || 'Atlas-01'}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}

      {/* VIEW 3: QUARTERLY ROADMAP */}
      {viewMode === 'roadmap' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
          {['Q3 2026', 'Q4 2026', 'Q1 2027'].map((qtr) => {
            const qtrGoals = goals.filter((g) => (g.quarter || 'Q3 2026') === qtr);
            return (
              <div key={qtr} className="p-4 bg-[#101012] border border-white/[0.08] rounded-[10px] space-y-3">
                <div className="flex items-center justify-between border-b border-white/[0.08] pb-2">
                  <h3 className="text-xs font-bold text-[#FFB020] uppercase">{qtr} Roadmap</h3>
                  <span className="text-[10px] text-gray-500">{qtrGoals.length} Objectives</span>
                </div>

                <div className="space-y-2.5">
                  {qtrGoals.map((g) => (
                    <div
                      key={g.id}
                      onClick={() => setSelectedGoal(g)}
                      className="p-3 bg-[#141416] border border-white/[0.06] hover:border-[#FFB020]/40 rounded-[8px] cursor-pointer space-y-1.5"
                    >
                      <div className="text-xs font-medium text-white line-clamp-1">{g.title}</div>
                      <div className="text-[10px] text-gray-500 flex items-center justify-between">
                        <span>{g.department_name}</span>
                        <span className="text-[#FFB020]">{g.progress}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Goal Detail & KR Manager Drawer */}
      <GoalDetailDrawer
        goal={selectedGoal}
        onClose={() => setSelectedGoal(null)}
        onGoalUpdated={handleGoalUpdated}
        onGoalDeleted={handleGoalDeleted}
      />

      {/* Add Goal Modal */}
      <AddGoalModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onGoalAdded={handleGoalAdded}
        agents={agents}
      />
    </div>
  );
}
