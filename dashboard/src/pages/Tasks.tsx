import { useState, useEffect } from 'react';
import {
  CheckSquare,
  Plus,
  Search,
  Columns,
  List,
  Play,
  Check,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Table } from '@/components/common/Table';
import { Modal } from '@/components/common/Modal';
import { Drawer } from '@/components/common/Drawer';
import { apiClient } from '@/api/client';
import type { Task } from '@/types/task';
import type { Agent } from '@/types/agent';

const defaultTasksMock: Task[] = [
  {
    id: 'task-1',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-core',
    title: 'Implement High-Throughput Redis Cache for Memory Stream',
    description: 'Optimize vector search memory lookups with 2-layer LRU cache and Redis serialization.',
    status: 'in_progress',
    priority: 1,
    assigned_agent_id: 'agent-bolt',
    parent_task_id: null,
    result: null,
    error: null,
    started_at: new Date(Date.now() - 3600000 * 4).toISOString(),
    completed_at: null,
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
    parent_task_id: null,
    result: null,
    error: null,
    started_at: new Date(Date.now() - 3600000 * 8).toISOString(),
    completed_at: null,
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
    parent_task_id: null,
    result: 'Audit completed. Zero critical vulnerabilities found.',
    error: null,
    started_at: new Date(Date.now() - 86400000).toISOString(),
    completed_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 86400000).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-4',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-core',
    title: 'Isometric Office Collision Mesh & Room Partition Shading',
    description: 'Ensure all doorway corridors, workstations, and meeting rooms have 0-collision navigation.',
    status: 'completed',
    priority: 2,
    assigned_agent_id: 'agent-pixel',
    parent_task_id: null,
    result: 'Collision polygon matrix built with sub-pixel doorway margins.',
    error: null,
    started_at: new Date(Date.now() - 86400000 * 2).toISOString(),
    completed_at: new Date().toISOString(),
    created_at: new Date(Date.now() - 86400000 * 2).toISOString(),
    updated_at: new Date().toISOString(),
  },
  {
    id: 'task-5',
    company_id: '00000000-0000-4000-8000-000000000001',
    project_id: 'proj-exec',
    title: 'Model Routing Cost Optimization & Tier Rebalancing',
    description: 'Rebalance tasks between GPT-4o-mini and Claude 3.7 to minimize cost-per-token by 28%.',
    status: 'pending',
    priority: 3,
    assigned_agent_id: 'agent-atlas',
    parent_task_id: null,
    result: null,
    error: null,
    started_at: null,
    completed_at: null,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  },
];

const defaultAgentsMock: Agent[] = [
  { id: 'agent-atlas', company_id: '00000000-0000-4000-8000-000000000001', name: 'Atlas-01', title: 'Chief Executive Officer', role: 'ceo', department_id: 'dept-exec', team_id: null, manager_id: null, status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['strategy', 'delegation'], responsibilities: 'Executive oversight', objectives: 'Company velocity', budget_monthly_cents: 50000, spent_monthly_cents: 18450, performance_score: 98, soul_description: 'Visionary leader', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-nova', company_id: '00000000-0000-4000-8000-000000000001', name: 'Nova-02', title: 'Chief Technology Officer', role: 'cto', department_id: 'dept-eng', team_id: null, manager_id: 'agent-atlas', status: 'active', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['architecture', 'review'], responsibilities: 'Tech leadership', objectives: 'Decoupled systems', budget_monthly_cents: 40000, spent_monthly_cents: 22100, performance_score: 96, soul_description: 'Pragmatic architect', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-bolt', company_id: '00000000-0000-4000-8000-000000000001', name: 'Bolt-03', title: 'Senior Backend Engineer', role: 'engineer', department_id: 'dept-eng', team_id: 'team-backend', manager_id: 'agent-nova', status: 'active', adapter_type: 'openai', model: 'gpt-4o', capabilities: ['nodejs', 'databases'], responsibilities: 'Backend microservices', objectives: 'Fast APIs', budget_monthly_cents: 30000, spent_monthly_cents: 14200, performance_score: 94, soul_description: 'Speed-first solver', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-pixel', company_id: '00000000-0000-4000-8000-000000000001', name: 'Pixel-04', title: 'Frontend & 3D Specialist', role: 'engineer', department_id: 'dept-eng', team_id: 'team-frontend', manager_id: 'agent-nova', status: 'active', adapter_type: 'openai', model: 'gpt-4o', capabilities: ['react', 'threejs'], responsibilities: '3D UI', objectives: 'Smooth interfaces', budget_monthly_cents: 25000, spent_monthly_cents: 9800, performance_score: 92, soul_description: 'UI craftsman', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-sage', company_id: '00000000-0000-4000-8000-000000000001', name: 'Sage-05', title: 'AI Research Lead', role: 'researcher', department_id: 'dept-ai', team_id: 'team-eval', manager_id: 'agent-atlas', status: 'idle', adapter_type: 'anthropic', model: 'claude-3-7-sonnet', capabilities: ['evals', 'rag'], responsibilities: 'AI Research', objectives: 'Prompt tuning', budget_monthly_cents: 40000, spent_monthly_cents: 18900, performance_score: 97, soul_description: 'Methodical researcher', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
  { id: 'agent-shield', company_id: '00000000-0000-4000-8000-000000000001', name: 'Shield-07', title: 'Security & QA Auditor', role: 'qa', department_id: 'dept-ops', team_id: 'team-qa-sec', manager_id: 'agent-forge', status: 'active', adapter_type: 'openai', model: 'gpt-4o-mini', capabilities: ['qa', 'security'], responsibilities: 'Security testing', objectives: 'Zero vulnerabilities', budget_monthly_cents: 15000, spent_monthly_cents: 7200, performance_score: 93, soul_description: 'Vigilant auditor', last_heartbeat_at: new Date().toISOString(), created_at: new Date().toISOString(), updated_at: new Date().toISOString() },
];

export function Tasks() {
  const [tasks, setTasks] = useState<Task[]>(defaultTasksMock);
  const [agents, setAgents] = useState<Agent[]>(defaultAgentsMock);
  const [viewMode, setViewMode] = useState<'board' | 'list'>('board');
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');

  // Selected task for drawer
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);

  // New task modal
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newAgent, setNewAgent] = useState('agent-bolt');
  const [newPriority, setNewPriority] = useState(2);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    let isMounted = true;
    async function loadData() {
      try {
        const [tasksRes, agentsRes] = await Promise.allSettled([
          apiClient.get<{ items: Task[] }>('/api/v1/companies/00000000-0000-4000-8000-000000000001/tasks'),
          apiClient.get<{ items: Agent[] }>('/api/v1/companies/00000000-0000-4000-8000-000000000001/agents'),
        ]);
        if (!isMounted) return;
        if (tasksRes.status === 'fulfilled' && tasksRes.value?.items?.length) {
          setTasks(tasksRes.value.items);
        }
        if (agentsRes.status === 'fulfilled' && agentsRes.value?.items?.length) {
          setAgents(agentsRes.value.items);
        }
      } catch (err) {
        // Silently use defaults
      }
    }
    loadData();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setCreating(true);
    try {
      const created = await apiClient.post<Task>(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/tasks',
        {
          title: newTitle,
          description: newDescription,
          assigned_agent_id: newAgent,
          priority: Number(newPriority),
          status: 'pending',
        }
      );
      setTasks((prev) => [created, ...prev]);
      setShowCreateModal(false);
      setNewTitle('');
      setNewDescription('');
    } catch (err) {
      console.error('Failed to create task', err);
    } finally {
      setCreating(false);
    }
  };

  const handleUpdateStatus = async (taskId: string, newStatus: Task['status']) => {
    try {
      const updated = await apiClient.patch<Task>(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/tasks/${taskId}`,
        { status: newStatus }
      );
      setTasks((prev) => prev.map((t) => (t.id === taskId ? updated : t)));
      if (selectedTask?.id === taskId) {
        setSelectedTask(updated);
      }
    } catch (err) {
      console.error('Failed to update task status', err);
    }
  };

  const filteredTasks = tasks.filter((t) => {
    if (statusFilter !== 'all' && t.status !== statusFilter) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      return (
        t.title.toLowerCase().includes(q) ||
        (t.description && t.description.toLowerCase().includes(q)) ||
        (t.assigned_agent_id && t.assigned_agent_id.toLowerCase().includes(q))
      );
    }
    return true;
  });

  const pendingTasks = filteredTasks.filter((t) => t.status === 'pending');
  const inProgressTasks = filteredTasks.filter((t) => t.status === 'in_progress');
  const completedTasks = filteredTasks.filter((t) => t.status === 'completed');

  return (
    <div className="space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <CheckSquare className="w-5 h-5 text-[#22C55E]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Task Operations Queue
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Autonomous execution board, dependency graphs, and agent assignments
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={15} />}
            onClick={() => setShowCreateModal(true)}
          >
            Create Task
          </Button>
        </div>
      </div>

      {/* Filter and View Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-[#101012] p-3 border border-white/[0.08] rounded-[8px]">
        <div className="flex items-center gap-2.5 flex-1 min-w-0">
          <div className="relative flex-1 max-w-sm">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search tasks or assignees..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs font-mono text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
          >
            <option value="all">All Columns</option>
            <option value="pending">Pending</option>
            <option value="in_progress">In Progress</option>
            <option value="completed">Completed</option>
          </select>
        </div>

        {/* View Mode Toggle */}
        <div className="flex items-center gap-1 bg-[#141416] border border-white/[0.08] p-0.5 rounded-[6px] shrink-0 self-end sm:self-auto">
          <button
            onClick={() => setViewMode('board')}
            className={`p-1.5 rounded-[4px] transition-colors cursor-pointer ${
              viewMode === 'board' ? 'bg-white/[0.08] text-[#FFB020]' : 'text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
            aria-label="Board view"
          >
            <Columns size={15} />
          </button>
          <button
            onClick={() => setViewMode('list')}
            className={`p-1.5 rounded-[4px] transition-colors cursor-pointer ${
              viewMode === 'list' ? 'bg-white/[0.08] text-[#FFB020]' : 'text-[#6B6B6E] hover:text-[#A8A8AB]'
            }`}
            aria-label="List view"
          >
            <List size={15} />
          </button>
        </div>
      </div>

      {/* Main Board or Table View */}
      {viewMode === 'board' ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
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
                    <span className="text-[10px] font-mono text-[#6B6B6E]">P{task.priority}</span>
                  </div>
                  {task.description && (
                    <p className="text-[11px] text-[#9C9C9F] line-clamp-2 leading-relaxed">
                      {task.description}
                    </p>
                  )}
                  <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[10px] font-mono text-[#6B6B6E]">
                    <span>{task.assigned_agent_id}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpdateStatus(task.id, 'in_progress');
                      }}
                      className="text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
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
                  className="p-4 bg-[#141416] border border-white/[0.08] hover:border-white/[0.2] rounded-[8px] space-y-2.5 cursor-pointer transition-all group"
                >
                  <div className="flex items-start justify-between gap-2">
                    <h4 className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#38BDF8] transition-colors">
                      {task.title}
                    </h4>
                    <span className="text-[10px] font-mono text-[#38BDF8]">Active</span>
                  </div>
                  {task.description && (
                    <p className="text-[11px] text-[#9C9C9F] line-clamp-2 leading-relaxed">
                      {task.description}
                    </p>
                  )}
                  <div className="flex items-center justify-between pt-2 border-t border-white/[0.04] text-[10px] font-mono text-[#6B6B6E]">
                    <span>{task.assigned_agent_id}</span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleUpdateStatus(task.id, 'completed');
                      }}
                      className="text-[#22C55E] hover:underline flex items-center gap-1 cursor-pointer"
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
                    <span>Assignee: {task.assigned_agent_id}</span>
                    <span>{new Date(task.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : (
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
              render: (t) => <span className="font-mono text-xs text-[#FFB020]">P{t.priority}</span>,
            },
            {
              key: 'assigned_agent_id',
              header: 'Assignee',
              render: (t) => (
                <span className="font-mono text-xs text-[#A8A8AB]">{t.assigned_agent_id}</span>
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

      {/* Task Inspection Drawer */}
      <Drawer
        isOpen={!!selectedTask}
        onClose={() => setSelectedTask(null)}
        title={selectedTask?.title || 'Task Details'}
        subtitle={`Task #${selectedTask?.id} · Priority P${selectedTask?.priority}`}
        footer={
          <div className="flex items-center justify-between gap-3">
            {selectedTask?.status === 'pending' && (
              <Button
                variant="primary"
                size="sm"
                className="w-full"
                onClick={() => selectedTask && handleUpdateStatus(selectedTask.id, 'in_progress')}
              >
                Start In-Progress
              </Button>
            )}
            {selectedTask?.status === 'in_progress' && (
              <Button
                variant="primary"
                size="sm"
                className="w-full"
                onClick={() => selectedTask && handleUpdateStatus(selectedTask.id, 'completed')}
              >
                Mark Completed
              </Button>
            )}
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setSelectedTask(null)}
            >
              Close
            </Button>
          </div>
        }
      >
        {selectedTask && (
          <div className="space-y-5">
            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                Objective Description
              </label>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs text-[#F2F1EE] leading-relaxed">
                {selectedTask.description || 'No detailed instructions specified.'}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Assigned Agent</div>
                <div className="text-[#FFB020] font-medium mt-1">{selectedTask.assigned_agent_id}</div>
              </div>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Status</div>
                <div className="mt-1">
                  <Badge variant={selectedTask.status as any}>{selectedTask.status}</Badge>
                </div>
              </div>
            </div>

            {selectedTask.result && (
              <div>
                <label className="text-[10px] font-mono text-[#22C55E] uppercase block mb-1">
                  Execution Output / Result
                </label>
                <div className="p-3 bg-[#101012] border border-[#22C55E]/30 rounded-[6px] text-xs font-mono text-[#22C55E] leading-relaxed">
                  {selectedTask.result}
                </div>
              </div>
            )}
          </div>
        )}
      </Drawer>

      {/* Create Task Modal */}
      <Modal
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
        title="Dispatch New Task"
      >
        <form onSubmit={handleCreateTask} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Task Title
            </label>
            <input
              type="text"
              value={newTitle}
              onChange={(e) => setNewTitle(e.target.value)}
              placeholder="e.g. Implement real-time Redis queue"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Assign Agent
              </label>
              <select
                value={newAgent}
                onChange={(e) => setNewAgent(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.name} ({a.title})
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Priority Level
              </label>
              <select
                value={newPriority}
                onChange={(e) => setNewPriority(Number(e.target.value))}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value={1}>P1 - Critical</option>
                <option value={2}>P2 - Standard</option>
                <option value={3}>P3 - Background</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Instructions & Acceptance Criteria
            </label>
            <textarea
              value={newDescription}
              onChange={(e) => setNewDescription(e.target.value)}
              rows={3}
              placeholder="Define input parameters and required deliverables..."
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
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
            <Button variant="primary" size="sm" type="submit" loading={creating}>
              Dispatch Task
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
