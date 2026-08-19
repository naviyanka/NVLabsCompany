import { Card } from '@/components/common/Card';
import {
  Users,
  Search,
  Plus,
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  Bell,
  Link as LinkIcon,
  Zap,
  Brain,
  Settings,
  BookOpen,
  AlertTriangle,
  Info,
  CheckCircle2,
} from 'lucide-react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const tabs = [
  'Overview',
  'Enhance Agents',
  'Skills & Abilities',
  'Memory Center',
  'Performance',
  'Templates',
  'Evaluations',
  'Settings',
];

const statCards = [
  { label: 'Total Agents', value: '32', change: '+4 this week', changeUp: true, percent: 75 },
  { label: 'Active', value: '24', badge: 'Running', changeUp: true, percent: 75 },
  { label: 'Under Training', value: '5', hasAlert: true, percent: 15 },
  { label: 'Inactive', value: '3', change: '↑ 10%', changeUp: true, percent: 9 },
  { label: 'Avg. Performance', value: '87%', change: '+6%', changeUp: true },
  { label: 'Skills', value: '128' },
  { label: 'Memory Items', value: '245.6K', change: '+18.4k', changeUp: true },
];

const sparklinePoints = [
  [4, 8, 6, 10, 8, 12, 14],
  [6, 7, 5, 9, 8, 10, 12],
  [3, 4, 3, 5, 4, 5, 6],
  [5, 4, 6, 4, 3, 4, 3],
];

const agents = [
  { name: 'Alpha', role: 'Backend Developer', badge: 'Developer', badgeColor: 'bg-purple-500/20 text-purple-400', backend: 'Gemini 1.5 Pro', status: 'Working', statusColor: 'bg-green-500/20 text-green-400', performance: 96, lastActive: '2m ago' },
  { name: 'Nova', role: 'Security Analyst', badge: 'Analyst', badgeColor: 'bg-blue-500/20 text-blue-400', backend: 'Claude 3.5 Sonnet', status: 'Working', statusColor: 'bg-green-500/20 text-green-400', performance: 91, lastActive: '5m ago' },
  { name: 'Cipher', role: 'Bug Bounty Hunter', badge: 'Hunter', badgeColor: 'bg-orange-500/20 text-orange-400', backend: 'GPT-4o', status: 'Review', statusColor: 'bg-red-500/20 text-red-400', performance: 87, lastActive: '13m ago' },
  { name: 'Omega', role: 'Researcher', badge: 'Researcher', badgeColor: 'bg-teal-500/20 text-teal-400', backend: 'Gemini 1.5 Pro', status: 'Working', statusColor: 'bg-green-500/20 text-green-400', performance: 89, lastActive: '1m ago' },
  { name: 'Vector', role: 'Data Engineer', badge: 'Engineer', badgeColor: 'bg-green-500/20 text-green-400', backend: 'Claude 3.5 Sonnet', status: 'Idle', statusColor: 'bg-yellow-500/20 text-yellow-400', performance: 66, lastActive: '45m ago' },
  { name: 'Shadow', role: 'Threat Intel Collector', badge: 'Collector', badgeColor: 'bg-purple-500/20 text-purple-400', backend: 'Mistral Large', status: 'Working', statusColor: 'bg-green-500/20 text-green-400', performance: 82, lastActive: '8m ago' },
  { name: 'Pulse', role: 'Automation Specialist', badge: 'Automation', badgeColor: 'bg-pink-500/20 text-pink-400', backend: 'Gemini 1.5 Flash', status: 'Training', statusColor: 'bg-orange-500/20 text-orange-400', performance: 71, lastActive: '3h ago' },
  { name: 'Echo', role: 'Content Strategist', badge: 'Strategist', badgeColor: 'bg-teal-500/20 text-teal-400', backend: 'Claude 3 Haiku', status: 'Idle', statusColor: 'bg-yellow-500/20 text-yellow-400', performance: 63, lastActive: '1h ago' },
];

const detailTabs = ['Overview', 'Skills', 'Memory', 'Tasks', 'Performance', 'Settings'];

const agentStats = [
  { label: 'Performance', value: '96%' },
  { label: 'Tasks Completed', value: '124' },
  { label: 'Avg. Response', value: '2.4s' },
  { label: 'Success Rate', value: '98.6%' },
  { label: 'Total Tokens', value: '1.24M' },
  { label: 'Uptime', value: '99.2%' },
];

const capabilities = ['Python', 'FastAPI', 'PostgreSQL', 'Docker', 'REST API', 'Authentication', 'JWT', 'Redis', 'Celery'];

const performanceData = [
  { date: 'May 10', value: 78 },
  { date: 'May 11', value: 82 },
  { date: 'May 12', value: 75 },
  { date: 'May 13', value: 87 },
  { date: 'May 14', value: 84 },
  { date: 'May 15', value: 80 },
  { date: 'May 16', value: 86 },
];

const enhanceActions = [
  { icon: <Zap size={18} className="text-yellow-400" />, title: 'Improve Skills', desc: 'Add new skills and capabilities' },
  { icon: <BookOpen size={18} className="text-blue-400" />, title: 'Train Agent', desc: 'Run training sessions' },
  { icon: <Brain size={18} className="text-purple-400" />, title: 'Optimize Memory', desc: 'Clean and optimize memory' },
  { icon: <Settings size={18} className="text-gray-400" />, title: 'Backend Settings', desc: 'Configure model & parameters' },
];

const memoryData = [
  { name: 'Conversations', value: 45, count: '170.9K', color: '#3b82f6' },
  { name: 'Knowledge', value: 25, count: '61.4K', color: '#10b981' },
  { name: 'Documents', value: 15, count: '36.8K', color: '#f59e0b' },
  { name: 'Code & Snippets', value: 10, count: '24.6K', color: '#8b5cf6' },
  { name: 'Other', value: 5, count: '11.2K', color: '#6b7280' },
];

const trainingQueue = [
  { agent: 'Nova', task: 'Security best practices', progress: 45 },
  { agent: 'Cipher', task: 'Advanced exploration', progress: 60 },
  { agent: 'Pulse', task: 'Workflow automation', progress: 30 },
];

const evaluations = [
  { agent: 'Alpha', title: 'Code Quality Evaluation', score: 96, time: 'May 16, 10:30 AM' },
  { agent: 'Nova', title: 'Security Assessment', score: 91, time: 'May 16, 08:15 AM' },
  { agent: 'Cipher', title: 'Bug Hunting Efficiency', score: 78, time: 'May 15, 04:45 PM' },
];

const skillDistributionData = [
  { name: 'Development', value: 42, count: 54, color: '#3b82f6' },
  { name: 'Security', value: 21, count: 27, color: '#f43f5e' },
  { name: 'Data & Analytics', value: 15, count: 19, color: '#10b981' },
  { name: 'Automation', value: 12, count: 15, color: '#f59e0b' },
  { name: 'Research', value: 10, count: 13, color: '#8b5cf6' },
];

const alerts = [
  { type: 'warning' as const, title: "Cipher's success rate dropped by 12%", desc: 'Review recent tasks and memory', time: '10m ago' },
  { type: 'info' as const, title: '5 agents can be trained on new skills', desc: 'Keep your agents up to date', time: '1h ago' },
  { type: 'success' as const, title: 'Memory optimization completed', desc: 'Recovered 2.4K memory items', time: '2h ago' },
];

// ─── Helper Components ─────────────────────────────────────────────────────────

function Sparkline({ points, color = '#10b981' }: { points: number[]; color?: string }) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const h = 24;
  const w = 48;
  const step = w / (points.length - 1);
  const pathPoints = points.map((p, i) => {
    const x = i * step;
    const y = h - ((p - min) / range) * h;
    return `${i === 0 ? 'M' : 'L'}${x},${y}`;
  }).join(' ');
  return (
    <svg width={w} height={h} className="inline-block">
      <path d={pathPoints} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function AlertIcon({ type }: { type: 'warning' | 'info' | 'success' }) {
  if (type === 'warning') return <AlertTriangle size={16} className="text-yellow-400" />;
  if (type === 'info') return <Info size={16} className="text-blue-400" />;
  return <CheckCircle2 size={16} className="text-green-400" />;
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function HRRoom() {
  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2">
          <Users size={24} className="text-teal-400" />
          <h1 className="text-2xl font-bold text-white">HR Room</h1>
        </div>
        <p className="text-sm text-gray-400 mt-1">Enhance, manage and empower your AI agents</p>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-white/[0.08]">
        <div className="flex items-center gap-1 overflow-x-auto">
          {tabs.map((tab) => (
            <button
              key={tab}
              className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                tab === 'Overview'
                  ? 'text-teal-400 border-b-2 border-teal-400'
                  : 'text-gray-400 hover:text-gray-300'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Stat Cards Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        {statCards.map((stat, idx) => (
          <Card key={stat.label} padding="sm">
            <p className="text-[10px] text-gray-400 uppercase tracking-wide">{stat.label}</p>
            <div className="flex items-center justify-between mt-1">
              <p className="text-lg font-bold text-white">{stat.value}</p>
              {idx < 4 && sparklinePoints[idx] && (
                <Sparkline points={sparklinePoints[idx]!} />
              )}
            </div>
            {stat.change && (
              <span className="text-[10px] text-green-400">{stat.change}</span>
            )}
            {stat.badge && (
              <span className="text-[10px] bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded">
                {stat.badge}
              </span>
            )}
            {stat.hasAlert && (
              <Bell size={12} className="text-yellow-400 mt-1" />
            )}
            {stat.percent !== undefined && (
              <div className="mt-1.5">
                <div className="h-1 bg-white/[0.08] rounded-full overflow-hidden">
                  <div
                    className="h-full bg-teal-500 rounded-full"
                    style={{ width: `${stat.percent}%` }}
                  />
                </div>
                <p className="text-[9px] text-gray-500 mt-0.5">{stat.percent}%</p>
              </div>
            )}
          </Card>
        ))}
      </div>

      {/* Main Three-Column Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
        {/* LEFT COLUMN - All Agents Table */}
        <Card className="lg:col-span-5" padding="none">
          <div className="p-4 border-b border-white/[0.08]">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold">All Agents</h3>
              <button className="flex items-center gap-1 px-3 py-1.5 bg-green-500/20 text-green-400 text-xs font-medium rounded-lg hover:bg-green-500/30 transition-colors">
                <Plus size={12} /> Add Agent
              </button>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex-1 flex items-center gap-2 px-3 py-1.5 bg-dark-bg rounded-lg border border-white/[0.05]">
                <Search size={14} className="text-gray-500" />
                <span className="text-xs text-gray-500">Search agents...</span>
              </div>
              <select className="px-2 py-1.5 bg-dark-bg border border-white/[0.05] rounded-lg text-xs text-gray-400 appearance-none">
                <option>All Roles</option>
              </select>
              <select className="px-2 py-1.5 bg-dark-bg border border-white/[0.05] rounded-lg text-xs text-gray-400 appearance-none">
                <option>All Status</option>
              </select>
              <select className="px-2 py-1.5 bg-dark-bg border border-white/[0.05] rounded-lg text-xs text-gray-400 appearance-none">
                <option>All Backends</option>
              </select>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  <th className="px-4 py-2 text-[10px] text-gray-500 uppercase font-medium">Agent</th>
                  <th className="px-2 py-2 text-[10px] text-gray-500 uppercase font-medium">Role</th>
                  <th className="px-2 py-2 text-[10px] text-gray-500 uppercase font-medium">Backend</th>
                  <th className="px-2 py-2 text-[10px] text-gray-500 uppercase font-medium">Status</th>
                  <th className="px-2 py-2 text-[10px] text-gray-500 uppercase font-medium">Perf</th>
                  <th className="px-2 py-2 text-[10px] text-gray-500 uppercase font-medium">Last Active</th>
                  <th className="px-2 py-2 text-[10px] text-gray-500 uppercase font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent) => (
                  <tr key={agent.name} className="border-b border-white/[0.05] hover:bg-white/[0.02]">
                    <td className="px-4 py-2">
                      <p className="text-xs text-white font-medium">{agent.name}</p>
                      <p className="text-[10px] text-gray-500">{agent.role}</p>
                    </td>
                    <td className="px-2 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${agent.badgeColor}`}>
                        {agent.badge}
                      </span>
                    </td>
                    <td className="px-2 py-2">
                      <span className="text-[10px] text-gray-400">{agent.backend}</span>
                    </td>
                    <td className="px-2 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded ${agent.statusColor}`}>
                        {agent.status}
                      </span>
                    </td>
                    <td className="px-2 py-2">
                      <span className="text-xs text-white">{agent.performance}%</span>
                    </td>
                    <td className="px-2 py-2">
                      <span className="text-[10px] text-gray-500">{agent.lastActive}</span>
                    </td>
                    <td className="px-2 py-2">
                      <button className="text-gray-500 hover:text-gray-300">
                        <MoreHorizontal size={14} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="px-4 py-3 flex items-center justify-between border-t border-white/[0.05]">
            <span className="text-[10px] text-gray-500">Showing 1 to 8 of 32 agents</span>
            <div className="flex items-center gap-1">
              <button className="w-6 h-6 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-6 h-6 flex items-center justify-center rounded bg-teal-500/20 text-teal-400 text-[10px]">1</button>
              <button className="w-6 h-6 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-6 h-6 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <button className="w-6 h-6 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">4</button>
              <button className="w-6 h-6 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronRight size={12} />
              </button>
            </div>
          </div>
        </Card>

        {/* CENTER COLUMN - Agent Detail Panel */}
        <Card className="lg:col-span-4" padding="none">
          {/* Agent Header */}
          <div className="p-4 border-b border-white/[0.08]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-10 h-10 bg-gradient-to-br from-green-400 to-green-600 rounded-full flex items-center justify-center">
                  <span className="text-white text-sm font-bold">A</span>
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-white font-semibold">Alpha</h3>
                    <span className="text-[10px] bg-green-500/20 text-green-400 px-1.5 py-0.5 rounded">Working</span>
                  </div>
                  <p className="text-xs text-gray-400">Backend Developer Agent</p>
                </div>
              </div>
              <button className="px-3 py-1.5 bg-white/[0.05] border border-white/[0.08] rounded-lg text-xs text-gray-400 hover:text-white transition-colors">
                Actions
              </button>
            </div>
            <div className="flex items-center gap-3 mt-3">
              <span className="text-[10px] text-gray-500">AGT-001</span>
              <span className="text-[10px] text-gray-500">•</span>
              <span className="text-[10px] text-gray-500">Created: 12 May 2024</span>
            </div>
            <div className="flex items-center gap-2 mt-2">
              <span className="text-[10px] bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded">Developer</span>
              <span className="text-[10px] bg-white/[0.05] text-gray-400 px-1.5 py-0.5 rounded flex items-center gap-1">
                <LinkIcon size={8} /> Gemini 1.5 Pro
              </span>
            </div>
          </div>

          {/* Detail Tabs */}
          <div className="px-4 border-b border-white/[0.05]">
            <div className="flex items-center gap-1 overflow-x-auto">
              {detailTabs.map((tab) => (
                <button
                  key={tab}
                  className={`px-3 py-2 text-[10px] font-medium whitespace-nowrap ${
                    tab === 'Overview'
                      ? 'text-teal-400 border-b border-teal-400'
                      : 'text-gray-500 hover:text-gray-300'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          {/* Stats Grid */}
          <div className="p-4 grid grid-cols-3 gap-3">
            {agentStats.map((stat) => (
              <div key={stat.label} className="bg-dark-bg rounded-lg p-2 border border-white/[0.05]">
                <p className="text-[9px] text-gray-500 uppercase">{stat.label}</p>
                <p className="text-sm font-bold text-white mt-0.5">{stat.value}</p>
              </div>
            ))}
          </div>

          {/* About Section */}
          <div className="px-4 pb-3">
            <h4 className="text-xs text-white font-medium mb-1">About Alpha</h4>
            <p className="text-[10px] text-gray-400 leading-relaxed mb-2">
              Specialized in building robust backend systems, APIs, and microservices.
            </p>
            <div className="flex flex-wrap gap-1">
              {capabilities.map((cap) => (
                <span key={cap} className="text-[9px] bg-white/[0.05] text-gray-400 px-1.5 py-0.5 rounded">
                  {cap}
                </span>
              ))}
              <span className="text-[9px] text-gray-500 px-1.5 py-0.5">+ 8 more</span>
            </div>
          </div>

          {/* Current Task */}
          <div className="px-4 pb-3">
            <div className="bg-dark-bg rounded-lg p-3 border border-white/[0.05]">
              <div className="flex items-center justify-between mb-1">
                <h4 className="text-xs text-white font-medium">Current Task</h4>
                <span className="text-[10px] text-teal-400 cursor-pointer">View Task</span>
              </div>
              <p className="text-[10px] text-gray-400 mb-2">Implement user authentication system</p>
              <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden mb-1">
                <div className="h-full bg-teal-500 rounded-full" style={{ width: '75%' }} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[9px] text-gray-500">Started 10:24 AM • Est. 25m remaining</span>
                <span className="text-[9px] text-teal-400">75%</span>
              </div>
            </div>
          </div>

          {/* Performance Chart */}
          <div className="px-4 pb-4">
            <div className="flex items-center justify-between mb-2">
              <h4 className="text-xs text-white font-medium">Performance Over Time</h4>
              <span className="text-[9px] text-gray-500 bg-white/[0.05] px-1.5 py-0.5 rounded">7 Days</span>
            </div>
            <div className="h-32">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={performanceData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis dataKey="date" stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} />
                  <YAxis stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} domain={[50, 100]} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1b2e',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      color: '#fff',
                      fontSize: '10px',
                    }}
                  />
                  <Line type="monotone" dataKey="value" stroke="#14b8a6" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </Card>

        {/* RIGHT COLUMN - Enhance / Memory / Training */}
        <div className="lg:col-span-3 space-y-4">
          {/* Enhance Agent */}
          <Card padding="lg">
            <h3 className="text-white font-semibold text-sm">Enhance Agent</h3>
            <p className="text-[10px] text-gray-400 mb-3">Upgrade and empower your agents</p>
            <div className="space-y-2">
              {enhanceActions.map((action) => (
                <div
                  key={action.title}
                  className="flex items-center gap-3 p-2 bg-dark-bg rounded-lg border border-white/[0.05] hover:border-white/[0.12] transition-colors cursor-pointer"
                >
                  <div className="w-8 h-8 flex items-center justify-center bg-white/[0.05] rounded-lg">
                    {action.icon}
                  </div>
                  <div>
                    <p className="text-xs text-white font-medium">{action.title}</p>
                    <p className="text-[10px] text-gray-500">{action.desc}</p>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-teal-400 mt-3 cursor-pointer">View Enhancement Tools &rarr;</p>
          </Card>

          {/* Memory Snapshot */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-1">
              <h3 className="text-white font-semibold text-sm">Memory Snapshot</h3>
            </div>
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs text-gray-400">245.6K Total Items</span>
              <span className="text-[10px] text-green-400">+18.6K this week</span>
            </div>
            <div className="h-36">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={memoryData}
                    cx="50%"
                    cy="50%"
                    innerRadius={35}
                    outerRadius={55}
                    dataKey="value"
                    stroke="none"
                  >
                    {memoryData.map((entry) => (
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
            </div>
            <div className="space-y-1 mt-2">
              {memoryData.map((item) => (
                <div key={item.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-[10px] text-gray-400">{item.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500">{item.value}% ({item.count})</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-teal-400 mt-3 cursor-pointer">View Memory Center &rarr;</p>
          </Card>

          {/* Training Queue */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">Training Queue</h3>
              <span className="text-[10px] text-teal-400 cursor-pointer">View All</span>
            </div>
            <div className="space-y-3">
              {trainingQueue.map((item) => (
                <div key={item.agent}>
                  <div className="flex items-center justify-between mb-1">
                    <div>
                      <span className="text-xs text-white font-medium">{item.agent}</span>
                      <span className="text-[10px] text-gray-500 ml-2">{item.task}</span>
                    </div>
                    <span className="text-[10px] text-gray-400">{item.progress}%</span>
                  </div>
                  <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div className="h-full bg-teal-500 rounded-full" style={{ width: `${item.progress}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-gray-500 mt-3">+ 2 more training sessions</p>
          </Card>
        </div>
      </div>

      {/* Bottom Three-Column Section */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Recent Evaluations */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-semibold text-sm">Recent Evaluations</h3>
            <span className="text-[10px] text-teal-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {evaluations.map((evaluation) => (
              <div key={evaluation.title} className="flex items-start gap-3 p-2 bg-dark-bg rounded-lg border border-white/[0.05]">
                <div className="w-8 h-8 bg-gradient-to-br from-teal-400 to-teal-600 rounded-full flex items-center justify-center flex-shrink-0">
                  <span className="text-white text-[10px] font-bold">{evaluation.agent[0]}</span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-white font-medium">{evaluation.agent}</p>
                  <p className="text-[10px] text-gray-400">{evaluation.title}</p>
                  <div className="flex items-center justify-between mt-1">
                    <span className="text-[10px] text-green-400">Score: {evaluation.score}%</span>
                    <span className="text-[9px] text-gray-500">{evaluation.time}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Skill Distribution */}
        <Card padding="lg">
          <h3 className="text-white font-semibold text-sm mb-3">Skill Distribution</h3>
          <div className="h-40 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={skillDistributionData}
                  cx="50%"
                  cy="50%"
                  innerRadius={40}
                  outerRadius={60}
                  dataKey="value"
                  stroke="none"
                >
                  {skillDistributionData.map((entry) => (
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
                <p className="text-lg font-bold text-white">128</p>
                <p className="text-[9px] text-gray-500">Total Skills</p>
              </div>
            </div>
          </div>
          <div className="space-y-1 mt-2">
            {skillDistributionData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-[10px] text-gray-400">{item.name}</span>
                </div>
                <span className="text-[10px] text-gray-500">{item.value}% ({item.count})</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Alerts & Recommendations */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-semibold text-sm">Alerts & Recommendations</h3>
            <span className="text-[10px] text-teal-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {alerts.map((alert) => (
              <div key={alert.title} className="flex items-start gap-3 p-2 bg-dark-bg rounded-lg border border-white/[0.05]">
                <div className="mt-0.5 flex-shrink-0">
                  <AlertIcon type={alert.type} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-white font-medium">{alert.title}</p>
                  <p className="text-[10px] text-gray-500">{alert.desc}</p>
                  <p className="text-[9px] text-gray-600 mt-1">{alert.time}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
