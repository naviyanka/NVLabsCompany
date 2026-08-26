import { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Users,
  CheckSquare,
  DollarSign,
  TrendingUp,
  Play,
  Plus,
  ArrowUpRight,
  GitPullRequest,
} from 'lucide-react';
import { ResponsiveContainer, ComposedChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient, unwrapItems } from '@/api/client';
import { getActiveCompanyId } from '@/config';

interface AgentItem {
  id: string;
  name: string;
  title: string;
  role: string;
  status: 'active' | 'idle' | 'paused';
  model: string;
  performance_score: number;
  spent_monthly_cents: number;
}

interface TaskItem {
  id: string;
  title: string;
  status: 'pending' | 'in_progress' | 'completed' | 'failed';
  priority: number;
  assigned_agent_id: string;
  created_at: string;
}

interface PipelineItem {
  id: string;
  name: string;
  status: 'idle' | 'running' | 'completed';
  success_rate: number;
  trigger: string;
}

const telemetryChartData = [
  { time: '00:00', tokens: 42000, cost: 12.4 },
  { time: '04:00', tokens: 28000, cost: 8.2 },
  { time: '08:00', tokens: 95000, cost: 28.5 },
  { time: '12:00', tokens: 142000, cost: 44.1 },
  { time: '16:00', tokens: 188000, cost: 58.2 },
  { time: '20:00', tokens: 110000, cost: 34.0 },
  { time: '24:00', tokens: 68000, cost: 21.3 },
];

const initialAgents: AgentItem[] = [];

const initialTasks: TaskItem[] = [];

const initialPipelines: PipelineItem[] = [];

export function Dashboard() {
  const navigate = useNavigate();
  const [agents, setAgents] = useState<AgentItem[]>(initialAgents);
  const [tasks, setTasks] = useState<TaskItem[]>(initialTasks);
  const [pipelines, setPipelines] = useState<PipelineItem[]>(initialPipelines);

  // Quick Action Modals
  const [showTaskModal, setShowTaskModal] = useState(false);
  const [showAgentModal, setShowAgentModal] = useState(false);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [newTaskAgent, setNewTaskAgent] = useState('agent-bolt');
  const [newAgentName, setNewAgentName] = useState('');
  const [newAgentTitle, setNewAgentTitle] = useState('');
  const [newAgentRole, setNewAgentRole] = useState('engineer');

  useEffect(() => {
    let isMounted = true;
    async function loadData() {
      try {
        const companyId = getActiveCompanyId();
        const [agentsRes, tasksRes, pipesRes] = await Promise.allSettled([
          apiClient.get<AgentItem[] | { items: AgentItem[] }>(`/api/v1/companies/${companyId}/agents`),
          apiClient.get<TaskItem[] | { items: TaskItem[] }>(`/api/v1/companies/${companyId}/tasks`),
          apiClient.get<PipelineItem[] | { items: PipelineItem[] }>(`/api/v1/companies/${companyId}/pipelines`),
        ]);
        if (!isMounted) return;

        if (agentsRes.status === 'fulfilled') {
          const items = unwrapItems(agentsRes.value);
          if (items.length) setAgents(items);
        }
        if (tasksRes.status === 'fulfilled') {
          const items = unwrapItems(tasksRes.value);
          if (items.length) setTasks(items);
        }
        if (pipesRes.status === 'fulfilled') {
          const items = unwrapItems(pipesRes.value);
          if (items.length) setPipelines(items);
        }
      } catch (err) {
        // Silently use defaults if offline
      }
    }
    loadData();
    return () => {
      isMounted = false;
    };
  }, []);

  const handleCreateTask = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newTaskTitle.trim()) return;
    try {
      const created = await apiClient.post<TaskItem>(`/api/v1/companies/${getActiveCompanyId()}/tasks`, {
        title: newTaskTitle,
        assigned_agent_id: newTaskAgent,
        status: 'pending',
        priority: 2,
      });
      setTasks((prev) => [created, ...prev]);
      setNewTaskTitle('');
      setShowTaskModal(false);
    } catch (err) {
      console.error('Task creation failed', err);
    }
  };

  const handleHireAgent = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newAgentName.trim()) return;
    try {
      const created = await apiClient.post<AgentItem>(`/api/v1/companies/${getActiveCompanyId()}/agents`, {
        name: newAgentName,
        title: newAgentTitle || 'Operations Specialist',
        role: newAgentRole,
      });
      setAgents((prev) => [created, ...prev]);
      setNewAgentName('');
      setNewAgentTitle('');
      setShowAgentModal(false);
    } catch (err) {
      console.error('Agent hire failed', err);
    }
  };

  const activeAgentsCount = agents.filter((a) => a.status === 'active').length;
  const completedTasksCount = tasks.filter((t) => t.status === 'completed').length;

  return (
    <div className="space-y-6">
      {/* Top Banner / Operational Command Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[#22C55E] animate-pulse" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Operations Control Deck
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Real-time telemetry, autonomous squads, and model execution routing
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<CheckSquare className="w-3.5 h-3.5 text-[#FFB020]" />}
            onClick={() => setShowTaskModal(true)}
          >
            Create Task
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Plus className="w-3.5 h-3.5" />}
            onClick={() => setShowAgentModal(true)}
          >
            Hire Agent
          </Button>
        </div>
      </div>

      {/* Metric Cards Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Active Workforce"
          value={`${activeAgentsCount} / ${agents.length || 8}`}
          subValue="Squad Units"
          change="+2 units active vs yesterday"
          changeType="positive"
          to="/agents"
          icon={<Users className="w-4 h-4" />}
        />
        <StatCard
          label="Operations Queue"
          value={tasks.length}
          subValue={`${completedTasksCount} completed`}
          change="98.2% completion SLA"
          changeType="positive"
          to="/tasks"
          icon={<CheckSquare className="w-4 h-4" />}
        />
        <StatCard
          label="Monthly Spend"
          value="$4,235"
          subValue="/ $10,000"
          change="42.3% threshold (Normal)"
          changeType="neutral"
          to="/budgets"
          icon={<DollarSign className="w-4 h-4" />}
        />
        <StatCard
          label="Evolution Proposals"
          value="2 Pending"
          subValue="Avg eval +18%"
          change="p < 0.01 statistical conf"
          changeType="positive"
          to="/evolution"
          icon={<TrendingUp className="w-4 h-4" />}
        />
      </div>

      {/* Main Operations Split: 2D Spatial Floor & Token Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: 2D Floorplan & Zone Routing (7 cols) */}
        <div className="lg:col-span-7">
          <Card
            header={
              <div className="flex items-center justify-between w-full">
                <div className="flex items-center gap-2">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#38BDF8]" />
                  <span className="text-xs font-mono font-medium text-[#F2F1EE] uppercase tracking-wider">
                    Workforce Spatial Zones
                  </span>
                </div>
                <Link
                  to="/office"
                  className="text-xs font-mono text-[#FFB020] hover:underline inline-flex items-center gap-1"
                >
                  Enter 3D Space <ArrowUpRight className="w-3 h-3" />
                </Link>
              </div>
            }
            padding="none"
          >
            <div className="p-4 bg-[#101012] border-b border-white/[0.04]">
              {/* Floorplan Layout Grid */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { name: 'Executive Suite', zone: 'exec', lead: 'Atlas-01', count: 2, status: 'nominal' },
                  { name: 'Engineering Core', zone: 'eng', lead: 'Nova-02', count: 3, status: 'high_load' },
                  { name: 'AI Reasoning Lab', zone: 'ai', lead: 'Sage-05', count: 1, status: 'nominal' },
                  { name: 'Ops & Security', zone: 'ops', lead: 'Shield-07', count: 2, status: 'nominal' },
                ].map((z) => (
                  <div
                    key={z.zone}
                    onClick={() => navigate('/office')}
                    className="p-3 bg-[#141416] border border-white/[0.08] rounded-[6px] hover:border-white/[0.2] transition-colors cursor-pointer"
                  >
                    <div className="flex items-center justify-between text-[11px] font-mono text-[#6B6B6E]">
                      <span>{z.name}</span>
                      <span className="w-1.5 h-1.5 rounded-full bg-[#22C55E]" />
                    </div>
                    <div className="mt-2 text-sm font-mono font-medium text-[#F2F1EE]">
                      {z.count} Agents
                    </div>
                    <div className="text-[10px] font-mono text-[#A8A8AB] mt-0.5">
                      Lead: {z.lead}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Agent Live Roster preview */}
            <div className="p-4 divide-y divide-white/[0.04] max-h-60 overflow-y-auto">
              {agents.slice(0, 4).map((agent) => (
                <div
                  key={agent.id}
                  onClick={() => navigate(`/agents/${agent.id}`)}
                  className="py-2.5 flex items-center justify-between hover:bg-white/[0.02] px-2 rounded cursor-pointer transition-colors"
                >
                  <div className="flex items-center gap-3">
                    <span className="w-2 h-2 rounded-full bg-[#22C55E]" />
                    <div>
                      <div className="text-xs font-medium text-[#F2F1EE]">{agent.name}</div>
                      <div className="text-[11px] font-mono text-[#6B6B6E]">{agent.title}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-4">
                    <span className="text-xs font-mono text-[#A8A8AB]">{agent.model}</span>
                    <Badge variant={agent.status === 'active' ? 'active' : 'idle'}>
                      {agent.status}
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Right: Telemetry & Token Rates (5 cols) */}
        <div className="lg:col-span-5">
          <Card
            header={
              <div className="flex items-center justify-between w-full">
                <span className="text-xs font-mono font-medium text-[#F2F1EE] uppercase tracking-wider">
                  Hourly Token Consumption
                </span>
                <span className="text-[11px] font-mono text-[#6B6B6E]">24H Aggregate</span>
              </div>
            }
          >
            <div className="h-56 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <ComposedChart data={telemetryChartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid stroke="#222" strokeDasharray="2 2" vertical={false} />
                  <XAxis dataKey="time" stroke="#6B6B6E" tick={{ fontSize: 10, fill: '#6B6B6E' }} />
                  <YAxis stroke="#6B6B6E" tick={{ fontSize: 10, fill: '#6B6B6E' }} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1C1C1F', borderColor: '#333', borderRadius: 6, fontSize: 11, color: '#F2F1EE' }}
                    labelStyle={{ color: '#FFB020', fontFamily: 'monospace' }}
                  />
                  <Line
                    type="monotone"
                    dataKey="tokens"
                    stroke="#FFB020"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4, fill: '#FFB020' }}
                  />
                </ComposedChart>
              </ResponsiveContainer>
            </div>

            <div className="pt-4 border-t border-white/[0.06] grid grid-cols-2 gap-4 text-center">
              <div>
                <div className="text-xs font-mono text-[#6B6B6E]">Peak Velocity</div>
                <div className="text-sm font-mono font-medium text-[#F2F1EE] mt-0.5">188k tokens/hr</div>
              </div>
              <div>
                <div className="text-xs font-mono text-[#6B6B6E]">Avg Unit Cost</div>
                <div className="text-sm font-mono font-medium text-[#22C55E] mt-0.5">$0.0031 / 1k</div>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Bottom Grid: Continuous Pipelines & Recent Operational Tasks */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Pipelines Card */}
        <Card
          header={
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-2">
                <GitPullRequest className="w-4 h-4 text-[#FFB020]" />
                <span className="text-xs font-mono font-medium text-[#F2F1EE] uppercase tracking-wider">
                  Automated Pipelines
                </span>
              </div>
              <Link to="/pipelines" className="text-xs font-mono text-[#FFB020] hover:underline">
                View All →
              </Link>
            </div>
          }
        >
          <div className="space-y-3">
            {pipelines.map((pipe) => (
              <div
                key={pipe.id}
                className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] flex items-center justify-between"
              >
                <div>
                  <div className="text-xs font-medium text-[#F2F1EE]">{pipe.name}</div>
                  <div className="text-[11px] font-mono text-[#6B6B6E] mt-0.5">
                    Trigger: {pipe.trigger} · SLA {pipe.success_rate}%
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Badge variant={pipe.status === 'running' ? 'in_progress' : 'completed'}>
                    {pipe.status}
                  </Badge>
                  <Button
                    variant="ghost"
                    size="xs"
                    icon={<Play className="w-3 h-3 text-[#FFB020]" />}
                    onClick={async () => {
                      await apiClient.post(`/api/v1/companies/${getActiveCompanyId()}/pipelines/${pipe.id}/trigger`);
                      setPipelines((prev) =>
                        prev.map((p) => (p.id === pipe.id ? { ...p, status: 'running' } : p))
                      );
                    }}
                  >
                    Run
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Tasks Queue Card */}
        <Card
          header={
            <div className="flex items-center justify-between w-full">
              <div className="flex items-center gap-2">
                <CheckSquare className="w-4 h-4 text-[#22C55E]" />
                <span className="text-xs font-mono font-medium text-[#F2F1EE] uppercase tracking-wider">
                  Active Task Queue
                </span>
              </div>
              <Link to="/tasks" className="text-xs font-mono text-[#FFB020] hover:underline">
                Board View →
              </Link>
            </div>
          }
        >
          <div className="space-y-2.5">
            {tasks.slice(0, 4).map((task) => (
              <div
                key={task.id}
                onClick={() => navigate('/tasks')}
                className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] flex items-center justify-between hover:bg-white/[0.02] cursor-pointer transition-colors"
              >
                <div className="min-w-0 pr-3">
                  <div className="text-xs font-medium text-[#F2F1EE] truncate">{task.title}</div>
                  <div className="text-[11px] font-mono text-[#6B6B6E] mt-0.5">
                    Assignee: {task.assigned_agent_id}
                  </div>
                </div>
                <Badge variant={task.status as any}>{task.status}</Badge>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Quick Action Modal: Create Task */}
      <Modal isOpen={showTaskModal} onClose={() => setShowTaskModal(false)} title="Assign New Task">
        <form onSubmit={handleCreateTask} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Task Title
            </label>
            <input
              type="text"
              value={newTaskTitle}
              onChange={(e) => setNewTaskTitle(e.target.value)}
              placeholder="e.g. Implement circuit breaker fallback"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Assign Agent
            </label>
            <select
              value={newTaskAgent}
              onChange={(e) => setNewTaskAgent(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.title})
                </option>
              ))}
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowTaskModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Dispatch Task
            </Button>
          </div>
        </form>
      </Modal>

      {/* Quick Action Modal: Hire Agent */}
      <Modal isOpen={showAgentModal} onClose={() => setShowAgentModal(false)} title="Hire Autonomous Agent">
        <form onSubmit={handleHireAgent} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Agent Call Sign / Name
            </label>
            <input
              type="text"
              value={newAgentName}
              onChange={(e) => setNewAgentName(e.target.value)}
              placeholder="e.g. Cipher-09"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Title & Specialization
            </label>
            <input
              type="text"
              value={newAgentTitle}
              onChange={(e) => setNewAgentTitle(e.target.value)}
              placeholder="e.g. Security Vulnerability Researcher"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Role Classification
            </label>
            <select
              value={newAgentRole}
              onChange={(e) => setNewAgentRole(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="engineer">Senior Engineer</option>
              <option value="researcher">AI Researcher</option>
              <option value="qa">Security & QA</option>
              <option value="devops">DevOps & SRE</option>
              <option value="pm">Project Coordinator</option>
            </select>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowAgentModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Deploy Agent
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
