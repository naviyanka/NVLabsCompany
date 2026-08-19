import { Card } from '@/components/common/Card';
import {
  Activity as ActivityIcon,
  BarChart3,
  CheckCircle2,
  XCircle,
  Clock,
  Users,
  Zap,
  Search,
  Filter,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  ExternalLink,
  Calendar,
  ArrowUp,
  ArrowDown,
} from 'lucide-react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const statCards = [
  { label: 'Total Activities', value: '2,842', change: '18.6%', changeUp: true, changeSuffix: 'vs last 7 days', icon: 'chart', iconBg: 'bg-pink-500/20', iconColor: 'text-pink-400' },
  { label: 'Successful Actions', value: '2,367', change: '16.3%', changeUp: true, changeSuffix: 'vs last 7 days', icon: 'check', iconBg: 'bg-green-500/20', iconColor: 'text-green-400' },
  { label: 'Failed Actions', value: '175', change: '9.4%', changeUp: false, changeSuffix: 'vs last 7 days', icon: 'x', iconBg: 'bg-red-500/20', iconColor: 'text-red-400' },
  { label: 'Avg. Response Time', value: '1.42s', change: '5.7%', changeUp: false, changeSuffix: 'vs last 7 days', icon: 'clock', iconBg: 'bg-blue-500/20', iconColor: 'text-blue-400' },
  { label: 'Active Users', value: '24', change: '', changeUp: true, changeSuffix: '', icon: 'users', iconBg: 'bg-teal-500/20', iconColor: 'text-teal-400' },
  { label: 'Events / Min (Avg)', value: '24.6', change: '14.2%', changeUp: true, changeSuffix: 'vs last 7 days', icon: 'zap', iconBg: 'bg-purple-500/20', iconColor: 'text-purple-400' },
];

const pageTabs = ['All Activity', 'System Events', 'Agent Activity', 'Task Activity', 'Pipeline Activity', 'User Activity'];

const activityRows = [
  { id: 1, event: 'Task Completed', typeBadge: 'Task', typeBadgeColor: 'bg-green-500/20 text-green-400', description: 'Bug bounty reconnaissance scan completed successfully.', metadata: 'Task ID: task_7fa2c9d4', agent: 'Cipher (Bug Bounty Hunter)', time: '10:24:32 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
  { id: 2, event: 'Pipeline Executed', typeBadge: 'Pipeline', typeBadgeColor: 'bg-blue-500/20 text-blue-400', description: 'AI Recon Pipeline executed', metadata: 'Pipeline ID: pipe_91ab2c3d', agent: 'Vector (Data Engineer)', time: '10:23:15 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
  { id: 3, event: 'Document Added', typeBadge: 'Knowledge Base', typeBadgeColor: 'bg-purple-500/20 text-purple-400', description: 'API Authentication Best Practices.md', metadata: 'Category: Security > Authentication', agent: 'Navi Yanka (Operator)', time: '10:21:47 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
  { id: 4, event: 'Task Failed', typeBadge: 'Task', typeBadgeColor: 'bg-red-500/20 text-red-400', description: 'SQL injection test failed', metadata: 'Task ID: task_3e7f1a2b', agent: 'Omega (Research Specialist)', time: '10:20:11 AM, May 16, 2024', status: 'Failed', statusColor: 'bg-red-500/20 text-red-400' },
  { id: 5, event: 'Code Pushed', typeBadge: 'Git Repo', typeBadgeColor: 'bg-teal-500/20 text-teal-400', description: 'Pushed 3 commits to mission-control', metadata: 'Branch: feature/activity-logs', agent: 'Navi Yanka (Operator)', time: '10:18:03 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
  { id: 6, event: 'Agent Started', typeBadge: 'Agent', typeBadgeColor: 'bg-orange-500/20 text-orange-400', description: 'Alpha agent started', metadata: 'Session ID: sess_7b3d9f6', agent: 'Alpha (Backend Developer)', time: '10:15:29 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
  { id: 7, event: 'Memory Updated', typeBadge: 'Memory', typeBadgeColor: 'bg-indigo-500/20 text-indigo-400', description: 'Added 5 new insights to attack graph', metadata: 'Memory ID: mem_45acd2f', agent: 'MemoryX (Memory Manager)', time: '10:14:08 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
  { id: 8, event: 'User Login', typeBadge: 'User', typeBadgeColor: 'bg-gray-500/20 text-gray-400', description: 'User logged in to the system', metadata: 'IP: 192.168.1.45', agent: 'Navi Yanka (Operator)', time: '10:12:33 AM, May 16, 2024', status: 'Success', statusColor: 'bg-green-500/20 text-green-400' },
];

const liveFeedItems = [
  { time: '10:25:12 AM', text: 'Pulse agent started task', detail: '', label: 'Agent: Pulse' },
  { time: '10:24:32 AM', text: 'Cipher completed task', detail: 'Task ID: task_7fa2c9d4', label: 'Agent: Cipher' },
  { time: '10:23:15 AM', text: 'Vector executed pipeline', detail: 'Pipeline ID: pipe_91ab2c3d', label: 'Agent: Vector' },
  { time: '10:22:08 AM', text: 'Omega created new memory', detail: 'Memory ID: mem_45acd2f', label: 'Agent: Omega' },
  { time: '10:21:47 AM', text: 'Navi Yanka added document', detail: 'API Authentication Best Practices.md', label: 'User' },
];

const activityByTypeData = [
  { name: 'Task', value: 1086, percentage: '38.2%', color: '#3b82f6' },
  { name: 'Pipeline', value: 609, percentage: '21.4%', color: '#10b981' },
  { name: 'System', value: 475, percentage: '18.7%', color: '#f59e0b' },
  { name: 'Agent', value: 341, percentage: '12.0%', color: '#14b8a6' },
  { name: 'User', value: 202, percentage: '7.1%', color: '#ec4899' },
  { name: 'Others', value: 129, percentage: '4.6%', color: '#6b7280' },
];

const topAgents = [
  { name: 'Cipher', count: 412, color: '#ef4444' },
  { name: 'Vector', count: 387, color: '#3b82f6' },
  { name: 'Omega', count: 354, color: '#10b981' },
  { name: 'Alpha', count: 298, color: '#f59e0b' },
  { name: 'Pulse', count: 265, color: '#8b5cf6' },
];

const quickFilters = [
  { label: 'Errors', dotColor: 'bg-red-400' },
  { label: 'Warnings', dotColor: 'bg-orange-400' },
  { label: 'Success', dotColor: 'bg-green-400' },
  { label: 'High Priority', dotColor: 'bg-red-400' },
  { label: 'My Activity', dotColor: 'bg-blue-400' },
  { label: 'Bookmarks', dotColor: 'bg-yellow-400' },
];

// ─── Helper Components ─────────────────────────────────────────────────────────

function StatCardIcon({ type, className }: { type: string; className: string }) {
  switch (type) {
    case 'chart':
      return <BarChart3 size={20} className={className} />;
    case 'check':
      return <CheckCircle2 size={20} className={className} />;
    case 'x':
      return <XCircle size={20} className={className} />;
    case 'clock':
      return <Clock size={20} className={className} />;
    case 'users':
      return <Users size={20} className={className} />;
    case 'zap':
      return <Zap size={20} className={className} />;
    default:
      return null;
  }
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function Activity() {
  return (
    <div className="flex gap-4">
      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <ActivityIcon size={24} className="text-indigo-400" />
              <h1 className="text-2xl font-bold text-white">Activity</h1>
            </div>
            <p className="text-sm text-gray-400 mt-1">Real-time overview of system activity and events across the platform</p>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              <Calendar size={14} />
              May 10 – May 16, 2024
              <ChevronDown size={14} />
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              Export
              <ChevronDown size={14} />
            </button>
          </div>
        </div>

        {/* Stat Cards Row */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {statCards.map((stat) => (
            <Card key={stat.label} padding="lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] text-gray-400 uppercase tracking-wide">{stat.label}</p>
                  <p className="text-xl font-bold text-white mt-1">{stat.value}</p>
                  {stat.change && (
                    <div className="flex items-center gap-1 mt-1">
                      {stat.changeUp ? (
                        <ArrowUp size={10} className="text-green-400" />
                      ) : (
                        <ArrowDown size={10} className={stat.label === 'Avg. Response Time' ? 'text-green-400' : 'text-red-400'} />
                      )}
                      <span className={`text-[10px] ${stat.changeUp || stat.label === 'Avg. Response Time' ? 'text-green-400' : 'text-red-400'}`}>
                        {stat.change} {stat.changeSuffix}
                      </span>
                    </div>
                  )}
                </div>
                <div className={`w-10 h-10 ${stat.iconBg} rounded-lg flex items-center justify-center`}>
                  <StatCardIcon type={stat.icon} className={stat.iconColor} />
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
                  tab === 'All Activity'
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
            <span className="text-sm text-gray-500">Search activity...</span>
          </div>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Types</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Agents</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Status</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Severity</option>
          </select>
          <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
            <Filter size={14} />
            Filters
          </button>
        </div>

        {/* Activity Table */}
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  <th className="px-4 py-3 text-[10px] text-gray-500 uppercase font-medium">Event</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Details</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Agent / User</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Time</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Status</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {activityRows.map((row) => (
                  <tr key={row.id} className="border-b border-white/[0.05] hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <p className="text-xs text-white font-medium">{row.event}</p>
                      <span className={`text-[10px] px-2 py-0.5 rounded mt-1 inline-block ${row.typeBadgeColor}`}>
                        {row.typeBadge}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <p className="text-xs text-gray-300">{row.description}</p>
                      <p className="text-[10px] text-gray-500 mt-0.5">{row.metadata}</p>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs text-gray-300">{row.agent}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-[10px] text-gray-500">{row.time}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`text-[10px] px-2 py-1 rounded ${row.statusColor}`}>
                        {row.status}
                      </span>
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
            <span className="text-[10px] text-gray-500">Showing 1 to 10 of 2,842 activities</span>
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded bg-indigo-500/20 text-indigo-400 text-[10px]">1</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">4</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">5</button>
              <span className="text-[10px] text-gray-500 px-1">...</span>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">285</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronRight size={12} />
              </button>
            </div>
            <select className="px-2 py-1 bg-dark-bg border border-white/[0.05] rounded text-[10px] text-gray-400 appearance-none">
              <option>10 / page</option>
            </select>
          </div>
        </Card>
      </div>

      {/* Right Sidebar */}
      <div className="w-80 flex-shrink-0 space-y-4">
        {/* Live Activity Feed */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h3 className="text-white font-semibold text-sm">Live Activity Feed</h3>
              <span className="flex items-center gap-1 text-[10px] text-green-400">
                <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                Live
              </span>
            </div>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {liveFeedItems.map((item, idx) => (
              <div key={idx} className="border-b border-white/[0.05] pb-3 last:border-0 last:pb-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-gray-500">{item.time}</span>
                </div>
                <p className="text-xs text-gray-300 mt-1">{item.text}</p>
                {item.detail && (
                  <p className="text-[10px] text-gray-500 mt-0.5">{item.detail}</p>
                )}
                <span className="text-[10px] text-indigo-400 mt-0.5 inline-block">{item.label}</span>
              </div>
            ))}
          </div>
          <button className="flex items-center gap-1 text-[10px] text-indigo-400 mt-4 hover:text-indigo-300 transition-colors">
            View Full Live Feed
            <ExternalLink size={10} />
          </button>
        </Card>

        {/* Activity by Type (7d) */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Activity by Type (7d)</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="h-44 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={activityByTypeData}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={65}
                  dataKey="value"
                  stroke="none"
                >
                  {activityByTypeData.map((entry) => (
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
                <p className="text-lg font-bold text-white">2,842</p>
                <p className="text-[9px] text-gray-500">Total</p>
              </div>
            </div>
          </div>
          <div className="space-y-1.5 mt-3">
            {activityByTypeData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-[10px] text-gray-400">{item.name}</span>
                </div>
                <span className="text-[10px] text-gray-500">
                  {item.percentage} ({item.value.toLocaleString()})
                </span>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Active Agents (7d) */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Top Active Agents (7d)</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {topAgents.map((agent, idx) => {
              const maxCount = topAgents[0]?.count ?? 1;
              const barWidth = (agent.count / maxCount) * 100;
              return (
                <div key={agent.name}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-500 w-4">{idx + 1}.</span>
                      <span className="text-xs text-white font-medium">{agent.name}</span>
                    </div>
                    <span className="text-[10px] text-gray-400">{agent.count} activities</span>
                  </div>
                  <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${barWidth}%`, backgroundColor: agent.color }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>

        {/* Quick Filters */}
        <Card padding="lg">
          <h3 className="text-white font-semibold text-sm mb-4">Quick Filters</h3>
          <div className="grid grid-cols-2 gap-2">
            {quickFilters.map((filter) => (
              <button
                key={filter.label}
                className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors"
              >
                <span className={`w-2 h-2 rounded-full ${filter.dotColor}`} />
                {filter.label}
              </button>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
