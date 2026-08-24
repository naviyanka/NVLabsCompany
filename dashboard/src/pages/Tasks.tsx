import { useState, useEffect, useMemo } from 'react';
import {
  CheckSquare,
  Plus,
  Search,
  Columns,
  List,
  Play,
  Check,
  BarChart3,
  Bot,
  ListChecks,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Table } from '@/components/common/Table';
import { apiClient, unwrapItems } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { Task } from '@/types/task';
import type { Agent } from '@/types/agent';
import { AddTaskModal } from '@/components/tasks/AddTaskModal';
import { TaskDetailDrawer } from '@/components/tasks/TaskDetailDrawer';

const MOCK_TASKS: Task[] = [
  {
    id: 'task-1',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-core',
    title: 'Implement High-Throughput Redis Cache for Vector Memory Stream',
    description: 'Optimize vector search memory lookups with 2-layer LRU cache and Redis serialization.',
    status: 'in_progress',
    priority: 1,
    assigned_agent_id: 'agent-bolt',
    subtasks: [
      { id: 'st-1', title: 'Implement Redis LRU caching layer', completed: true },
      { id: 'st-2', title: 'Benchmark serialization latency under 50ms', completed: false },
    ],
    started_at: new Date(Date.now() - 3600000 * 4).toISOString(),
    created_at: new Date(Date.now() - 3600000 * 4).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-2',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-ai',
    title: 'Benchmarking Multi-Agent Reasoning Chains (Claude 3.7 vs GPT-4o)',
    description: 'Execute statistical evaluation matrix across 250 coding and architectural decision scenarios.',
    status: 'in_progress',
    priority: 2,
    assigned_agent_id: 'agent-sage',
    subtasks: [
      { id: 'st-3', title: 'Prepare 250 evaluation benchmarks', completed: true },
      { id: 'st-4', title: 'Aggregate cost and latency stats', completed: false },
    ],
    started_at: new Date(Date.now() - 3600000 * 8).toISOString(),
    created_at: new Date(Date.now() - 3600000 * 8).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-3',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-sec',
    title: 'Automated Dependency Vulnerability & API Gatekeeper Audit',
    description: 'Scan npm/pip packages, inspect RBAC permissions, and verify token signing policies.',
    status: 'completed',
    priority: 1,
    assigned_agent_id: 'agent-shield',
    result: 'Audit completed cleanly. Zero critical vulnerabilities found.',
    subtasks: [
      { id: 'st-5', title: 'Audit npm package tree for CVEs', completed: true },
      { id: 'st-6', title: 'Verify JWT RS256 token signatures', completed: true },
    ],
    started_at: new Date(Date.now() - 86400000).toISOString(),
    completed_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-4',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-core',
    title: 'Model Routing Cost Optimization & Tier Rebalancing',
    description: 'Rebalance tasks between GPT-4o-mini and Claude 3.7 to minimize cost-per-token by 28%.',
    status: 'pending',
    priority: 3,
    assigned_agent_id: 'agent-atlas',
    subtasks: [
      { id: 'st-7', title: 'Analyze token usage metrics', completed: false },
      { id: 'st-8', title: 'Update model routing configuration', completed: false },
    ],
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const MOCK_AGENTS: Agent[] = [
  { id: 'agent-atlas', company_id: '00000000-0000-4000-8000-000000000001', name: 'Atlas-01', title: 'Chief Executive Officer', role: 'ceo', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', budget_monthly_cents: 50000, spent_monthly_cents: 18450, performance_score: 98 } as any,
  { id: 'agent-nova', company_id: '00000000-0000-4000-8000-000000000001', name: 'Nova-02', title: 'Chief Technology Officer', role: 'cto', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', budget_monthly_cents: 40000, spent_monthly_cents: 22100, performance_score: 96 } as any,
  { id: 'agent-bolt', company_id: '00000000-0000-4000-8000-000000000001', name: 'Bolt-03', title: 'Senior Backend Engineer', role: 'engineer', status: 'active', adapter_type: 'openai', model: 'gpt-4o', budget_monthly_cents: 30000, spent_monthly_cents: 14200, performance_score: 94 } as any,
  { id: 'agent-pixel', company_id: '00000000-0000-4000-8000-000000000001', name: 'Pixel-04', title: 'Frontend Specialist', role: 'engineer', status: 'active', adapter_type: 'openai', model: 'gpt-4o', budget_monthly_cents: 25000, spent_monthly_cents: 9800, performance_score: 92 } as any,
  { id: 'agent-sage', company_id: '00000000-0000-4000-8000-000000000001', name: 'Sage-05', title: 'AI Research Lead', role: 'researcher', status: 'idle', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', budget_monthly_cents: 40000, spent_monthly_cents: 18900, performance_score: 97 } as any,
  { id: 'agent-shield', company_id: '00000000-0000-4000-8000-000000000001', name: 'Shield-07', title: 'Security Auditor', role: 'qa', status: 'active', adapter_type: 'openai', model: 'gpt-4o-mini', budget_monthly_cents: 15000, spent_monthly_cents: 7200, performance_score: 93 } as any,
];

export function Tasks() {
  const [tasks, setTasks] = useState<Task[]>(MOCK_TASKS);
  const [agents, setAgents] = useState<Agent[]>(MOCK_AGENTS);
  const [viewMode, setViewMode] = useState<'board' | 'table' | 'workload'>('board');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [priorityFilter, setPriorityFilter] = useState('all');

  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [showAddModal, setShowAddModal] = useState(false);

  useEffect(() => {
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const [tasksRes, agentsRes] = await Promise.allSettled([
          apiClient.get<Task[] | { items: Task[] }>(`/api/v1/companies/${companyId}/tasks`),
          apiClient.get<Agent[] | { items: Agent[] }>(`/api/v1/companies/${companyId}/agents`),
        ]);

        if (tasksRes.status === 'fulfilled') {
          const items = unwrapItems(tasksRes.value);
          if (items.length) setTasks(items);
        }
        if (agentsRes.status === 'fulfilled') {
          const items = unwrapItems(agentsRes.value);
          if (items.length) setAgents(items);
        }
      } catch (err) {
        console.error('Failed to load tasks', err);
      }
    }
    loadData();
  }, []);

  const handleTaskCreated = (newTask: Task) => {
    setTasks((prev) => [newTask, ...prev]);
  };

  const handleTaskUpdated = (updatedTask: Task) => {
    setTasks((prev) => prev.map((t) => (t.id === updatedTask.id ? updatedTask : t)));
    if (selectedTask?.id === updatedTask.id) {
      setSelectedTask(updatedTask);
    }
  };

  const handleTaskDeleted = (taskId: string) => {
    setTasks((prev) => prev.filter((t) => t.id !== taskId));
    if (selectedTask?.id === taskId) {
      setSelectedTask(null);
    }
  };

  const handleUpdateStatus = async (taskId: string, newStatus: Task['status']) => {
    const target = tasks.find((t) => t.id === taskId);
    if (!target) return;

    const updatedTask: Task = {
      ...target,
      status: newStatus,
      completed_at: newStatus === 'completed' ? new Date().toISOString() : target.completed_at,
      updated_at: new Date().toISOString(),
    };

    handleTaskUpdated(updatedTask);

    try {
      await apiClient.patch<Task>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/tasks/${taskId}`,
        { status: newStatus, completed_at: updatedTask.completed_at }
      );
    } catch (err) {
      console.error('Failed to update task status', err);
    }
  };

  const filteredTasks = useMemo(() => {
    return tasks.filter((t) => {
      if (statusFilter !== 'all' && t.status !== statusFilter) return false;
      if (priorityFilter !== 'all' && t.priority !== Number(priorityFilter)) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return (
          t.title.toLowerCase().includes(q) ||
          (t.description && t.description.toLowerCase().includes(q)) ||
          (t.assigned_agent_id && t.assigned_agent_id.toLowerCase().includes(q))
        );
      }
      return true;
    });
  }, [tasks, statusFilter, priorityFilter, searchQuery]);

  const pendingTasks = filteredTasks.filter((t) => t.status === 'pending');
  const inProgressTasks = filteredTasks.filter((t) => t.status === 'in_progress');
  const completedTasks = filteredTasks.filter((t) => t.status === 'completed');

  /* Agent Workload Heatmap Data */
  const agentWorkloadMap = useMemo(() => {
    const map: Record<string, { total: number; active: number; done: number }> = {};
    agents.forEach((a) => {
      map[a.id] = { total: 0, active: 0, done: 0 };
    });
    tasks.forEach((t) => {
      const aid = t.assigned_agent_id || 'agent-bolt';
      if (!map[aid]) map[aid] = { total: 0, active: 0, done: 0 };
      map[aid].total++;
      if (t.status === 'in_progress') map[aid].active++;
      if (t.status === 'completed') map[aid].done++;
    });
    return map;
  }, [tasks, agents]);

  return (
    <div className="space-y-6 font-sans">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <CheckSquare className="w-5 h-5 text-[#22C55E]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Task Operations Queue & Agent Workload Management
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Autonomous task execution queue, sub-task deliverables, and agent workload dispatch
          </p>
        </div>

        <Button
          variant="primary"
          size="sm"
          icon={<Plus size={15} />}
          onClick={() => setShowAddModal(true)}
        >
          Dispatch Task
        </Button>
      </div>

      {/* Metrics Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Total Queue Tasks</span>
            <CheckSquare size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-white mt-1">{tasks.length} Directives</div>
          <p className="text-[10px] text-gray-500 mt-1">Sub-tasks tracked</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Active In-Progress</span>
            <Bot size={14} className="text-[#38BDF8]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#38BDF8] mt-1">
            {tasks.filter((t) => t.status === 'in_progress').length} Active
          </div>
          <p className="text-[10px] text-gray-500 mt-1">Autonomous solvers running</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Completed SLA</span>
            <Check size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">
            {tasks.filter((t) => t.status === 'completed').length} Resolved
          </div>
          <p className="text-[10px] text-gray-500 mt-1">100% verified output</p>
        </div>

        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Agent Utilization</span>
            <BarChart3 size={14} className="text-purple-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-purple-400 mt-1">87.5%</div>
          <p className="text-[10px] text-gray-500 mt-1">Workload balanced</p>
        </div>
      </div>

      {/* Filter and View Mode Control Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 bg-[#101012] p-3 border border-white/[0.08] rounded-[8px]">
        <div className="flex items-center gap-2 flex-1 min-w-0">
          {/* Search */}
          <div className="relative flex-1 max-w-sm">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search tasks, descriptions, assignees..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs font-mono text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          >
            <option value="all">All Statuses</option>
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="completed">Completed</option>
          </select>

          {/* Priority Filter */}
          <select
            value={priorityFilter}
            onChange={(e) => setPriorityFilter(e.target.value)}
            className="px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs font-mono text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          >
            <option value="all">All Priorities</option>
            <option value="1">P1 - Critical</option>
            <option value="2">P2 - Standard</option>
            <option value="3">P3 - Background</option>
          </select>
        </div>

        {/* View Switcher */}
        <div className="flex items-center bg-[#141416] border border-white/[0.08] rounded p-0.5">
          <button
            onClick={() => setViewMode('board')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
              viewMode === 'board' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
            }`}
          >
            <Columns size={13} /> Kanban Board
          </button>
          <button
            onClick={() => setViewMode('table')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
              viewMode === 'table' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
            }`}
          >
            <List size={13} /> Matrix Table
          </button>
          <button
            onClick={() => setViewMode('workload')}
            className={`px-2.5 py-1 rounded text-xs font-mono flex items-center gap-1 transition-colors cursor-pointer ${
              viewMode === 'workload' ? 'bg-[#FFB020] text-black font-bold' : 'text-gray-400 hover:text-white'
            }`}
          >
            <BarChart3 size={13} /> Agent Workload
          </button>
        </div>
      </div>

      {/* VIEW 1: KANBAN BOARD VIEW */}
      {viewMode === 'board' && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 font-sans">
          {/* Column: Pending */}
          <div className="space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-white/[0.08]">
              <div className="flex items-center gap-2 text-xs font-mono font-medium text-[#6B6B6E] uppercase">
                <span className="w-2 h-2 rounded-full bg-[#6B6B6E]" />
                <span>Pending ({pendingTasks.length})</span>
              </div>
            </div>

            <div className="space-y-2.5">
              {pendingTasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => setSelectedTask(task)}
                  className="p-4 bg-[#141416] border border-white/[0.08] hover:border-white/[0.2] rounded-[8px] space-y-2.5 cursor-pointer transition-all group"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                      {task.title}
                    </h4>
                    <span className="text-[10px] font-mono text-[#FFB020] font-bold">P{task.priority}</span>
                  </div>
                  {task.description && (
                    <p className="text-[11px] text-[#9C9C9F] line-clamp-2 leading-relaxed">
                      {task.description}
                    </p>
                  )}

                  {/* Subtask indicator */}
                  {task.subtasks && task.subtasks.length > 0 && (
                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-gray-400">
                      <ListChecks size={12} className="text-[#FFB020]" />
                      <span>
                        {task.subtasks.filter((s) => s.completed).length}/{task.subtasks.length} subtasks
                      </span>
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[10px] font-mono text-[#6B6B6E]">
                    <span>Agent: {task.assigned_agent_id || 'Atlas-01'}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpdateStatus(task.id, 'in_progress');
                      }}
                      className="text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer font-bold"
                    >
                      <Play size={10} /> Start
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Column: In Progress */}
          <div className="space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-white/[0.08]">
              <div className="flex items-center gap-2 text-xs font-mono font-medium text-[#38BDF8] uppercase">
                <span className="w-2 h-2 rounded-full bg-[#38BDF8]" />
                <span>In Progress ({inProgressTasks.length})</span>
              </div>
            </div>

            <div className="space-y-2.5">
              {inProgressTasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => setSelectedTask(task)}
                  className="p-4 bg-[#141416] border border-[#38BDF8]/40 hover:border-[#38BDF8] rounded-[8px] space-y-2.5 cursor-pointer transition-all group"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#38BDF8] transition-colors">
                      {task.title}
                    </h4>
                    <span className="text-[10px] font-mono text-[#38BDF8] font-bold">Active</span>
                  </div>
                  {task.description && (
                    <p className="text-[11px] text-[#9C9C9F] line-clamp-2 leading-relaxed">
                      {task.description}
                    </p>
                  )}

                  {/* Subtask indicator */}
                  {task.subtasks && task.subtasks.length > 0 && (
                    <div className="flex items-center gap-1.5 text-[10px] font-mono text-gray-400">
                      <ListChecks size={12} className="text-[#38BDF8]" />
                      <span>
                        {task.subtasks.filter((s) => s.completed).length}/{task.subtasks.length} subtasks
                      </span>
                    </div>
                  )}

                  <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[10px] font-mono text-[#6B6B6E]">
                    <span>Agent: {task.assigned_agent_id || 'Bolt-03'}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpdateStatus(task.id, 'completed');
                      }}
                      className="text-[#22C55E] hover:underline flex items-center gap-1 cursor-pointer font-bold"
                    >
                      <Check size={11} /> Complete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Column: Completed */}
          <div className="space-y-3">
            <div className="flex items-center justify-between pb-2 border-b border-white/[0.08]">
              <div className="flex items-center gap-2 text-xs font-mono font-medium text-[#22C55E] uppercase">
                <span className="w-2 h-2 rounded-full bg-[#22C55E]" />
                <span>Completed ({completedTasks.length})</span>
              </div>
            </div>

            <div className="space-y-2.5">
              {completedTasks.map((task) => (
                <div
                  key={task.id}
                  onClick={() => setSelectedTask(task)}
                  className="p-4 bg-[#141416] border border-white/[0.08] hover:border-white/[0.2] rounded-[8px] space-y-2.5 cursor-pointer transition-all group opacity-85 hover:opacity-100"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-xs font-medium text-[#F2F1EE] line-through decoration-white/30">
                      {task.title}
                    </h4>
                    <Badge variant="completed">Done</Badge>
                  </div>
                  {task.result && (
                    <p className="text-[11px] font-mono text-[#22C55E] line-clamp-2 leading-relaxed">
                      {task.result}
                    </p>
                  )}
                  <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[10px] font-mono text-[#6B6B6E]">
                    <span>Agent: {task.assigned_agent_id || 'Shield-07'}</span>
                    <span>{new Date(task.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* VIEW 2: DATA TABLE MATRIX VIEW */}
      {viewMode === 'table' && (
        <Table
          data={filteredTasks}
          keyExtractor={(t) => t.id}
          onRowClick={(t) => setSelectedTask(t)}
          columns={[
            {
              key: 'title',
              header: 'Task Objective',
              sortable: true,
              render: (t) => (
                <div>
                  <div className="font-medium text-[#F2F1EE]">{t.title}</div>
                  {t.description && (
                    <div className="text-[11px] text-[#6B6B6E] line-clamp-1">{t.description}</div>
                  )}
                </div>
              ),
            },
            {
              key: 'status',
              header: 'Status',
              sortable: true,
              render: (t) => <Badge variant={t.status as any}>{t.status}</Badge>,
            },
            {
              key: 'priority',
              header: 'Priority',
              render: (t) => <span className="font-mono text-xs text-[#FFB020] font-bold">P{t.priority}</span>,
            },
            {
              key: 'assigned_agent_id',
              header: 'Assignee',
              render: (t) => (
                <span className="font-mono text-xs text-[#A8A8AB]">{t.assigned_agent_id || 'Atlas-01'}</span>
              ),
            },
            {
              key: 'updated_at',
              header: 'Updated',
              align: 'right',
              render: (t) => (
                <span className="font-mono text-xs text-[#6B6B6E]">
                  {new Date(t.updated_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              ),
            },
          ]}
        />
      )}

      {/* VIEW 3: AGENT WORKLOAD HEATMAP */}
      {viewMode === 'workload' && (
        <div className="space-y-4 font-mono text-xs">
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2 mb-1">
              <BarChart3 className="w-4 h-4 text-purple-400" />
              Autonomous Agent Workload & Dispatch Distribution Matrix
            </h3>
            <p className="text-xs text-gray-400">
              Real-time monitoring of assigned task loads, active solvers, and SLA resolution velocity
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {agents.map((agent) => {
              const stats = agentWorkloadMap[agent.id] || { total: 0, active: 0, done: 0 };
              return (
                <div
                  key={agent.id}
                  className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-3"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <div className="text-white font-bold text-xs">{agent.name}</div>
                      <div className="text-[10px] text-gray-400">{agent.title}</div>
                    </div>
                    <Badge variant={stats.active > 0 ? 'in_progress' : 'completed'}>
                      {stats.active > 0 ? 'Busy' : 'Idle'}
                    </Badge>
                  </div>

                  <div className="grid grid-cols-3 gap-2 pt-2 border-t border-white/[0.06] text-center text-[10px]">
                    <div className="p-2 bg-[#0C0C0E] rounded">
                      <div className="text-gray-400">Total Tasks</div>
                      <div className="text-white font-bold text-xs mt-0.5">{stats.total}</div>
                    </div>
                    <div className="p-2 bg-[#0C0C0E] rounded">
                      <div className="text-gray-400">Active</div>
                      <div className="text-[#38BDF8] font-bold text-xs mt-0.5">{stats.active}</div>
                    </div>
                    <div className="p-2 bg-[#0C0C0E] rounded">
                      <div className="text-gray-400">Resolved</div>
                      <div className="text-emerald-400 font-bold text-xs mt-0.5">{stats.done}</div>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Task Inspection Drawer */}
      <TaskDetailDrawer
        task={selectedTask}
        onClose={() => setSelectedTask(null)}
        onTaskUpdated={handleTaskUpdated}
        onTaskDeleted={handleTaskDeleted}
        agents={agents}
      />

      {/* Add Task Modal */}
      <AddTaskModal
        isOpen={showAddModal}
        onClose={() => setShowAddModal(false)}
        onTaskCreated={handleTaskCreated}
        agents={agents}
      />
    </div>
  );
}
