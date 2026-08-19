import { Card } from '@/components/common/Card';
import {
  ClipboardList,
  CheckCircle2,
  Clock,
  XCircle,
  Search,
  Filter,
  Plus,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  MoreHorizontal,
  ArrowUp,
  ArrowDown,
  Copy,
  Maximize2,
  X,
  Square,
  RefreshCw,
  Loader2,
  Columns,
} from 'lucide-react';
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const taskStats = [
  { label: 'Total Tasks', value: '356', change: '14% this week', changeUp: true, icon: 'clipboard', iconBg: 'bg-red-500/20', iconColor: 'text-red-400' },
  { label: 'Completed', value: '198', subtitle: '55.6%', icon: 'check', iconBg: 'bg-green-500/20', iconColor: 'text-green-400', percent: 55.6, color: '#10b981' },
  { label: 'In Progress', value: '98', subtitle: '27.5%', icon: 'progress', iconBg: 'bg-blue-500/20', iconColor: 'text-blue-400', percent: 27.5, color: '#3b82f6' },
  { label: 'Pending', value: '42', subtitle: '11.8%', icon: 'clock', iconBg: 'bg-orange-500/20', iconColor: 'text-orange-400', percent: 11.8, color: '#f59e0b' },
  { label: 'Failed / Blocked', value: '18', subtitle: '5.1%', icon: 'x', iconBg: 'bg-red-500/20', iconColor: 'text-red-400', percent: 5.1, color: '#ef4444' },
];

const pageTabs = ['All Tasks', 'My Tasks', 'Assigned to Agents', 'Completed', 'Blocked'];

const tasks = [
  { id: 1, name: 'Subdomain Enumeration', category: 'Recon', pipeline: 'Bug Bounty Recon', pipelineColor: 'bg-orange-500/20 text-orange-400', agent: 'Alpha', priority: 'High', priorityColor: 'text-red-400', status: 'Completed', statusColor: 'bg-green-500/20 text-green-400', statusIcon: 'check', progress: 100, updated: '10:24 AM' },
  { id: 2, name: 'Analyze target.com', category: 'Analysis', pipeline: 'Code Review Auto', pipelineColor: 'bg-blue-500/20 text-blue-400', agent: 'Nova', priority: 'High', priorityColor: 'text-red-400', status: 'In Progress', statusColor: 'bg-blue-500/20 text-blue-400', statusIcon: 'progress', progress: 75, updated: '10:21 AM' },
  { id: 3, name: 'Generate attack vectors', category: 'AI Analysis', pipeline: 'Threat Intel', pipelineColor: 'bg-purple-500/20 text-purple-400', agent: 'Cipher', priority: 'Medium', priorityColor: 'text-orange-400', status: 'In Progress', statusColor: 'bg-blue-500/20 text-blue-400', statusIcon: 'progress', progress: 60, updated: '10:18 AM' },
  { id: 4, name: 'Sensitive Data Scan', category: 'Security', pipeline: 'Data Leak Detection', pipelineColor: 'bg-teal-500/20 text-teal-400', agent: 'Omega', priority: 'High', priorityColor: 'text-red-400', status: 'Completed', statusColor: 'bg-green-500/20 text-green-400', statusIcon: 'check', progress: 100, updated: '10:15 AM' },
  { id: 5, name: 'Repository Code Audit', category: 'Code Review', pipeline: 'Code Review Auto', pipelineColor: 'bg-blue-500/20 text-blue-400', agent: 'Vector', priority: 'Medium', priorityColor: 'text-orange-400', status: 'In Progress', statusColor: 'bg-blue-500/20 text-blue-400', statusIcon: 'progress', progress: 40, updated: '10:10 AM' },
  { id: 6, name: 'WAF Detection', category: 'Recon', pipeline: 'Bug Bounty Recon', pipelineColor: 'bg-orange-500/20 text-orange-400', agent: 'Shadow', priority: 'Low', priorityColor: 'text-green-400', status: 'Pending', statusColor: 'bg-yellow-500/20 text-yellow-400', statusIcon: 'pending', progress: 0, updated: '10:05 AM' },
  { id: 7, name: 'Exploit Suggestion', category: 'Exploitation', pipeline: 'Exploit Generator', pipelineColor: 'bg-red-500/20 text-red-400', agent: 'Pulse', priority: 'High', priorityColor: 'text-red-400', status: 'Blocked', statusColor: 'bg-red-500/20 text-red-400', statusIcon: 'blocked', progress: 10, updated: '09:58 AM' },
  { id: 8, name: 'Report Generation', category: 'Reporting', pipeline: 'Report Automation', pipelineColor: 'bg-gray-500/20 text-gray-400', agent: 'Echo', priority: 'Low', priorityColor: 'text-green-400', status: 'Pending', statusColor: 'bg-yellow-500/20 text-yellow-400', statusIcon: 'pending', progress: 0, updated: '09:45 AM' },
];

const statusChartData = [
  { name: 'Completed', value: 198, color: '#10b981' },
  { name: 'In Progress', value: 98, color: '#3b82f6' },
  { name: 'Pending', value: 42, color: '#f59e0b' },
  { name: 'Failed / Blocked', value: 18, color: '#ef4444' },
];

const priorityChartData = [
  { name: 'High', value: 200, color: '#ef4444' },
  { name: 'Medium', value: 120, color: '#f59e0b' },
  { name: 'Low', value: 36, color: '#10b981' },
];

const topAgents = [
  { name: 'Alpha', tasks: 86 },
  { name: 'Nova', tasks: 72 },
  { name: 'Cipher', tasks: 54 },
  { name: 'Omega', tasks: 48 },
  { name: 'Others', tasks: 96 },
];

const detailTabs = ['Overview', 'Subtasks (5)', 'Artifacts (3)', 'Logs'];

const activityItems = [
  { text: 'Task started by Alpha', time: '10:21 AM' },
  { text: 'Assigned to Nova', time: '10:21 AM' },
  { text: 'Subtask 1 completed', time: '10:28 AM' },
  { text: 'Scanning technologies...', time: '10:32 AM' },
  { text: 'Found 12 new endpoints', time: '10:35 AM' },
];

// ─── Helper Components ─────────────────────────────────────────────────────────

function StatIcon({ type, className }: { type: string; className: string }) {
  switch (type) {
    case 'clipboard':
      return <ClipboardList size={20} className={className} />;
    case 'check':
      return <CheckCircle2 size={20} className={className} />;
    case 'progress':
      return <Loader2 size={20} className={className} />;
    case 'clock':
      return <Clock size={20} className={className} />;
    case 'x':
      return <XCircle size={20} className={className} />;
    default:
      return null;
  }
}

function CircularProgress({ percent, color, size = 36 }: { percent: number; color: string; size?: number }) {
  const radius = (size - 4) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;
  return (
    <svg width={size} height={size} className="transform -rotate-90">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.08)"
        strokeWidth="3"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        fill="none"
        stroke={color}
        strokeWidth="3"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
      />
    </svg>
  );
}

function StatusIcon({ type }: { type: string }) {
  switch (type) {
    case 'check':
      return <CheckCircle2 size={12} />;
    case 'progress':
      return <Loader2 size={12} />;
    case 'pending':
      return <Clock size={12} />;
    case 'blocked':
      return <XCircle size={12} />;
    default:
      return null;
  }
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function Tasks() {
  return (
    <div className="flex gap-4">
      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ClipboardList size={24} className="text-indigo-400" />
              <h1 className="text-2xl font-bold text-white">Tasks</h1>
            </div>
            <p className="text-sm text-gray-400 mt-1">Track and manage all tasks across your AI workforce</p>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              <Filter size={14} />
              Filters
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              Group: None
              <ChevronDown size={14} />
            </button>
            <button className="flex items-center gap-2 px-4 py-2 bg-[#10b981] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
              <Plus size={16} />
              Create Task
            </button>
          </div>
        </div>

        {/* Stat Cards Row */}
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-5 gap-4">
          {taskStats.map((stat) => (
            <Card key={stat.label} padding="lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] text-gray-400 uppercase tracking-wide">{stat.label}</p>
                  <p className="text-xl font-bold text-white mt-1">{stat.value}</p>
                  {stat.change && (
                    <div className="flex items-center gap-1 mt-1">
                      <ArrowUp size={10} className="text-green-400" />
                      <span className="text-[10px] text-green-400">{stat.change}</span>
                    </div>
                  )}
                  {stat.subtitle && (
                    <p className="text-[10px] text-gray-500 mt-1">{stat.subtitle}</p>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {stat.percent !== undefined && stat.color && (
                    <CircularProgress percent={stat.percent} color={stat.color} />
                  )}
                  {!stat.percent && (
                    <div className={`w-10 h-10 ${stat.iconBg} rounded-lg flex items-center justify-center`}>
                      <StatIcon type={stat.icon} className={stat.iconColor} />
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-white/[0.08]">
          <div className="flex items-center gap-1">
            {pageTabs.map((tab) => (
              <button
                key={tab}
                className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                  tab === 'All Tasks'
                    ? 'text-indigo-400 border-b-2 border-indigo-400'
                    : 'text-gray-400 hover:text-gray-300'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg">
            <Search size={14} className="text-gray-500" />
            <span className="text-sm text-gray-500">Search tasks...</span>
          </div>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Status</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Agents</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Pipelines</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Priority</option>
          </select>
          <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
            <Columns size={14} />
            Columns
          </button>
        </div>

        {/* Tasks Table */}
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  <th className="px-4 py-3 w-8">
                    <input type="checkbox" className="rounded border-white/[0.2] bg-transparent" />
                  </th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Task</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Pipeline</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Agent</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Priority</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Status</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Progress</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Updated</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {tasks.map((task) => (
                  <tr key={task.id} className="border-b border-white/[0.05] hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <input type="checkbox" className="rounded border-white/[0.2] bg-transparent" />
                    </td>
                    <td className="px-3 py-3">
                      <p className="text-xs text-white font-medium">{task.name}</p>
                      <p className="text-[10px] text-gray-500">{task.category}</p>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`text-[10px] px-2 py-1 rounded ${task.pipelineColor}`}>
                        {task.pipeline}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs text-gray-300">{task.agent}</span>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1">
                        {task.priority === 'Low' ? (
                          <ArrowDown size={10} className={task.priorityColor} />
                        ) : (
                          <ArrowUp size={10} className={task.priorityColor} />
                        )}
                        <span className={`text-xs ${task.priorityColor}`}>{task.priority}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`text-[10px] px-2 py-1 rounded inline-flex items-center gap-1 ${task.statusColor}`}>
                        <StatusIcon type={task.statusIcon} />
                        {task.status}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${task.progress}%`,
                              backgroundColor: task.progress === 100 ? '#10b981' : task.progress > 0 ? '#3b82f6' : 'transparent',
                            }}
                          />
                        </div>
                        <span className="text-[10px] text-gray-400">{task.progress}%</span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-[10px] text-gray-500">{task.updated}</span>
                    </td>
                    <td className="px-3 py-3">
                      <button className="text-gray-500 hover:text-gray-300">
                        <MoreHorizontal size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 flex items-center justify-between border-t border-white/[0.05]">
            <span className="text-[10px] text-gray-500">Showing 1 to 8 of 356 tasks</span>
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded bg-indigo-500/20 text-indigo-400 text-[10px]">1</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">4</button>
              <span className="text-[10px] text-gray-500 px-1">...</span>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">45</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronRight size={12} />
              </button>
            </div>
            <select className="px-2 py-1 bg-dark-bg border border-white/[0.05] rounded text-[10px] text-gray-400 appearance-none">
              <option>10 / page</option>
            </select>
          </div>
        </Card>

        {/* Bottom Three-Column Section */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Tasks by Status - Donut Chart */}
          <Card padding="lg">
            <h3 className="text-white font-semibold text-sm mb-3">Tasks by Status</h3>
            <div className="h-44 relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={statusChartData}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={65}
                    dataKey="value"
                    stroke="none"
                  >
                    {statusChartData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1b2e',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      color: '#fff',
                      fontSize: '10px',
                    }}
                  />
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-center">
                  <p className="text-lg font-bold text-white">356</p>
                  <p className="text-[9px] text-gray-500">Total</p>
                </div>
              </div>
            </div>
            <div className="space-y-1.5 mt-3">
              {statusChartData.map((item) => (
                <div key={item.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-[10px] text-gray-400">{item.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500">
                    {item.value} ({((item.value / 356) * 100).toFixed(1)}%)
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Tasks by Priority - Horizontal Bar Chart */}
          <Card padding="lg">
            <h3 className="text-white font-semibold text-sm mb-3">Tasks by Priority</h3>
            <div className="h-44">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={priorityChartData} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <XAxis type="number" stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} domain={[0, 200]} />
                  <YAxis type="category" dataKey="name" stroke="#6b7280" fontSize={10} tickLine={false} axisLine={false} width={60} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1b2e',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      color: '#fff',
                      fontSize: '10px',
                    }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {priorityChartData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* Top Agents by Tasks - Leaderboard */}
          <Card padding="lg">
            <h3 className="text-white font-semibold text-sm mb-3">Top Agents by Tasks</h3>
            <div className="space-y-3">
              {topAgents.map((agent, idx) => {
                const maxTasks = Math.max(...topAgents.filter(a => a.name !== 'Others').map(a => a.tasks));
                const barWidth = (agent.tasks / maxTasks) * 100;
                return (
                  <div key={agent.name}>
                    <div className="flex items-center justify-between mb-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] text-gray-500 w-4">{idx + 1}.</span>
                        <span className="text-xs text-white font-medium">{agent.name}</span>
                      </div>
                      <span className="text-xs text-gray-400">{agent.tasks}</span>
                    </div>
                    <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-indigo-500 rounded-full"
                        style={{ width: `${barWidth}%` }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>
      </div>

      {/* Right Sidebar - Task Details Panel */}
      <div className="w-80 flex-shrink-0">
        <Card padding="none" className="sticky top-4">
          {/* Panel Header */}
          <div className="p-4 border-b border-white/[0.08]">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Task Details</span>
              <div className="flex items-center gap-2">
                <button className="text-gray-500 hover:text-gray-300">
                  <Maximize2 size={14} />
                </button>
                <button className="text-gray-500 hover:text-gray-300">
                  <X size={14} />
                </button>
              </div>
            </div>
          </div>

          {/* Task Title Section */}
          <div className="p-4 border-b border-white/[0.05]">
            <div className="flex items-center gap-2 mb-2">
              <h3 className="text-white font-semibold text-sm">Analyze target.com</h3>
              <span className="text-[10px] bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded inline-flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                In Progress
              </span>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-gray-500">task_7f2a9c4d</span>
                <button className="text-gray-500 hover:text-gray-300">
                  <Copy size={10} />
                </button>
              </div>
            </div>
            <p className="text-[10px] text-gray-500 mt-1">Created: May 16, 2024 10:20 AM</p>
          </div>

          {/* Detail Tabs */}
          <div className="px-4 border-b border-white/[0.05]">
            <div className="flex items-center gap-1 overflow-x-auto">
              {detailTabs.map((tab) => (
                <button
                  key={tab}
                  className={`px-3 py-2 text-[10px] font-medium whitespace-nowrap ${
                    tab === 'Overview'
                      ? 'text-indigo-400 border-b border-indigo-400'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          {/* Description */}
          <div className="p-4 border-b border-white/[0.05]">
            <h4 className="text-[10px] text-gray-500 uppercase tracking-wide mb-2">Description</h4>
            <p className="text-xs text-gray-300 leading-relaxed">
              Perform in-depth analysis of target.com including technologies, endpoints, and potential vulnerabilities.
            </p>
          </div>

          {/* Metadata Grid */}
          <div className="p-4 border-b border-white/[0.05]">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-[9px] text-gray-500 uppercase">Pipeline</p>
                <p className="text-xs text-blue-400 mt-0.5">Code Review Auto</p>
              </div>
              <div>
                <p className="text-[9px] text-gray-500 uppercase">Agent</p>
                <p className="text-xs text-white mt-0.5">Nova (Security Analyst)</p>
              </div>
              <div>
                <p className="text-[9px] text-gray-500 uppercase">Priority</p>
                <div className="flex items-center gap-1 mt-0.5">
                  <ArrowUp size={10} className="text-red-400" />
                  <span className="text-xs text-red-400">High</span>
                </div>
              </div>
              <div>
                <p className="text-[9px] text-gray-500 uppercase">Status</p>
                <div className="flex items-center gap-1 mt-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
                  <span className="text-xs text-blue-400">In Progress</span>
                </div>
              </div>
              <div className="col-span-2">
                <p className="text-[9px] text-gray-500 uppercase">Progress</p>
                <div className="flex items-center gap-2 mt-1">
                  <div className="flex-1 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: '75%' }} />
                  </div>
                  <span className="text-[10px] text-gray-400">75%</span>
                </div>
              </div>
              <div>
                <p className="text-[9px] text-gray-500 uppercase">Started</p>
                <p className="text-xs text-gray-300 mt-0.5">10:21 AM, May 16</p>
              </div>
              <div>
                <p className="text-[9px] text-gray-500 uppercase">Est. Completion</p>
                <p className="text-xs text-gray-300 mt-0.5">10:46 AM, May 16</p>
              </div>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="p-4 border-b border-white/[0.05]">
            <h4 className="text-[10px] text-gray-500 uppercase tracking-wide mb-3">Quick Actions</h4>
            <div className="grid grid-cols-2 gap-2">
              <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                <RefreshCw size={12} />
                Reassign Task
              </button>
              <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                <ArrowUp size={12} />
                Change Priority
              </button>
              <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                <Plus size={12} />
                Add Subtask
              </button>
              <button className="flex items-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-[10px] text-red-400 hover:border-red-500/40 transition-colors">
                <Square size={12} />
                Stop Task
              </button>
            </div>
          </div>

          {/* Task Activity */}
          <div className="p-4 border-b border-white/[0.05]">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-[10px] text-gray-500 uppercase tracking-wide">Task Activity</h4>
              <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
            </div>
            <div className="space-y-3">
              {activityItems.map((item, idx) => (
                <div key={idx} className="flex items-start gap-2">
                  <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-[10px] text-gray-300">{item.text}</p>
                    <p className="text-[9px] text-gray-500">{item.time}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Related Tasks */}
          <div className="p-4">
            <div className="flex items-center justify-between mb-3">
              <h4 className="text-[10px] text-gray-500 uppercase tracking-wide">Related Tasks</h4>
              <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
            </div>
            <div className="flex items-center justify-between p-2 bg-dark-bg rounded-lg border border-white/[0.05]">
              <span className="text-xs text-white">Subdomain Enumeration</span>
              <span className="text-[10px] bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
                <CheckCircle2 size={10} />
                Completed
              </span>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
