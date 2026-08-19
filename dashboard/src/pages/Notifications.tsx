import { Card } from '@/components/common/Card';
import {
  Bell,
  Search,
  Filter,
  ChevronLeft,
  ChevronRight,
  MoreHorizontal,
  AlertTriangle,
  ArrowDown,
  Bot,
  GitBranch,
  AlertCircle,
  Brain,
  FileText,
  AtSign,
  UserPlus,
  Shield,
  Rocket,
  Server,
  Database,
  Settings,
} from 'lucide-react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const categoryTabs = [
  { label: 'All', count: 12, active: true },
  { label: 'Unread', count: 8, active: false },
  { label: 'Mentions', count: 2, active: false },
  { label: 'Alerts', count: 3, active: false },
  { label: 'System', count: 5, active: false },
];

const notificationRows = [
  {
    id: 1,
    title: 'Agent Alpha completed task',
    description: 'User authentication system implementation completed successfully.',
    module: 'Agents',
    moduleBadgeColor: 'bg-blue-500/20 text-blue-400',
    priority: 'Success',
    priorityColor: 'bg-green-400',
    time: '2m ago',
    icon: Bot,
    iconBg: 'bg-green-500/20',
    iconColor: 'text-green-400',
  },
  {
    id: 2,
    title: 'New pull request created',
    description: 'Omega created pull request #128 in agent-core repository',
    module: 'Git Repos',
    moduleBadgeColor: 'bg-teal-500/20 text-teal-400',
    priority: 'Medium',
    priorityColor: 'bg-orange-400',
    time: '15m ago',
    icon: GitBranch,
    iconBg: 'bg-purple-500/20',
    iconColor: 'text-purple-400',
  },
  {
    id: 3,
    title: 'Pipeline execution failed',
    description: 'AI Recon Pipeline failed at step: Subdomain Enumeration',
    module: 'Pipelines',
    moduleBadgeColor: 'bg-blue-500/20 text-blue-400',
    priority: 'High',
    priorityColor: 'bg-red-400',
    time: '22m ago',
    icon: AlertCircle,
    iconBg: 'bg-red-500/20',
    iconColor: 'text-red-400',
  },
  {
    id: 4,
    title: 'New memory insight generated',
    description: 'Vector stored 5 new insights for attack graph',
    module: 'Memory',
    moduleBadgeColor: 'bg-indigo-500/20 text-indigo-400',
    priority: 'Low',
    priorityColor: 'bg-green-400',
    time: '35m ago',
    icon: Brain,
    iconBg: 'bg-purple-500/20',
    iconColor: 'text-purple-400',
  },
  {
    id: 5,
    title: 'Document added to Knowledge Base',
    description: 'API Authentication Best Practices.md added',
    module: 'Knowledge Base',
    moduleBadgeColor: 'bg-purple-500/20 text-purple-400',
    priority: 'Medium',
    priorityColor: 'bg-orange-400',
    time: '1h ago',
    icon: FileText,
    iconBg: 'bg-green-500/20',
    iconColor: 'text-green-400',
  },
  {
    id: 6,
    title: 'High error rate detected',
    description: 'Error rate above 5% in agent-service',
    module: 'System',
    moduleBadgeColor: 'bg-gray-500/20 text-gray-400',
    priority: 'High',
    priorityColor: 'bg-red-400',
    time: '1h 15m ago',
    icon: AlertCircle,
    iconBg: 'bg-red-500/20',
    iconColor: 'text-red-400',
  },
  {
    id: 7,
    title: 'You were mentioned by Vector',
    description: '@Navi Yanka please review the pipeline configuration',
    module: 'Mentions',
    moduleBadgeColor: 'bg-blue-500/20 text-blue-400',
    priority: 'Medium',
    priorityColor: 'bg-orange-400',
    time: '2h ago',
    icon: AtSign,
    iconBg: 'bg-blue-500/20',
    iconColor: 'text-blue-400',
  },
  {
    id: 8,
    title: 'New user registered',
    description: 'User johndoe@nvlabs.dev joined the platform',
    module: 'System',
    moduleBadgeColor: 'bg-gray-500/20 text-gray-400',
    priority: 'Low',
    priorityColor: 'bg-green-400',
    time: '3h ago',
    icon: UserPlus,
    iconBg: 'bg-gray-500/20',
    iconColor: 'text-gray-400',
  },
  {
    id: 9,
    title: 'Security scan completed',
    description: 'No vulnerabilities found in agent-core repository',
    module: 'Git Repos',
    moduleBadgeColor: 'bg-teal-500/20 text-teal-400',
    priority: 'Success',
    priorityColor: 'bg-green-400',
    time: '5h ago',
    icon: Shield,
    iconBg: 'bg-green-500/20',
    iconColor: 'text-green-400',
  },
  {
    id: 10,
    title: 'Deployment successful',
    description: 'Memory service deployed to production environment',
    module: 'System',
    moduleBadgeColor: 'bg-gray-500/20 text-gray-400',
    priority: 'Success',
    priorityColor: 'bg-green-400',
    time: '6h ago',
    icon: Rocket,
    iconBg: 'bg-green-500/20',
    iconColor: 'text-green-400',
  },
  {
    id: 11,
    title: 'High memory usage alert',
    description: 'Memory Usage is above 85% on server mem-02',
    module: 'System',
    moduleBadgeColor: 'bg-gray-500/20 text-gray-400',
    priority: 'High',
    priorityColor: 'bg-red-400',
    time: '7h ago',
    icon: Server,
    iconBg: 'bg-red-500/20',
    iconColor: 'text-red-400',
  },
  {
    id: 12,
    title: 'Database backup completed',
    description: 'Daily backup completed successfully',
    module: 'System',
    moduleBadgeColor: 'bg-gray-500/20 text-gray-400',
    priority: 'Success',
    priorityColor: 'bg-green-400',
    time: '8h ago',
    icon: Database,
    iconBg: 'bg-green-500/20',
    iconColor: 'text-green-400',
  },
];

const summaryChartData = [
  { name: 'Success', value: 42, percentage: '28%', color: '#10b981' },
  { name: 'Alerts', value: 23, percentage: '16%', color: '#ef4444' },
  { name: 'System', value: 38, percentage: '26%', color: '#3b82f6' },
  { name: 'Updates', value: 28, percentage: '19%', color: '#f59e0b' },
  { name: 'Mentions', value: 17, percentage: '11%', color: '#8b5cf6' },
];

const priorityBreakdown = [
  { label: 'High Priority', count: 23, percentage: '16%', color: 'text-red-400', bgColor: 'bg-red-500/20', icon: 'up' },
  { label: 'Medium Priority', count: 56, percentage: '38%', color: 'text-orange-400', bgColor: 'bg-orange-500/20', icon: 'up' },
  { label: 'Low Priority', count: 69, percentage: '46%', color: 'text-green-400', bgColor: 'bg-green-500/20', icon: 'down' },
];

const recentUnread = [
  { title: 'Pipeline execution failed', dotColor: 'bg-red-400', time: '22m ago' },
  { title: 'High error rate detected', dotColor: 'bg-red-400', time: '1h 15m ago' },
  { title: 'You were mentioned by Vector', dotColor: 'bg-blue-400', time: '2h ago' },
  { title: 'High memory usage alert', dotColor: 'bg-orange-400', time: '7h ago' },
];

// ─── Main Component ────────────────────────────────────────────────────────────

export function Notifications() {
  return (
    <div className="flex gap-4">
      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Bell size={24} className="text-indigo-400" />
              <h1 className="text-2xl font-bold text-white">Notifications</h1>
            </div>
            <p className="text-sm text-gray-400 mt-1">Stay updated with important events and activities across the platform</p>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              Mark all as read
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-sm text-red-400 hover:bg-red-500/30 transition-colors">
              <Settings size={14} />
              Notification Settings
            </button>
          </div>
        </div>

        {/* Category Tabs */}
        <div className="flex items-center gap-2">
          {categoryTabs.map((tab) => (
            <button
              key={tab.label}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                tab.active
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'bg-dark-surface border border-white/[0.08] text-gray-400 hover:text-white'
              }`}
            >
              {tab.label}
              <span className={`text-[10px] ${tab.active ? 'text-blue-400' : 'text-gray-500'}`}>
                {tab.count}
              </span>
            </button>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg">
            <Search size={14} className="text-gray-500" />
            <span className="text-sm text-gray-500">Search notifications...</span>
          </div>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Types</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Modules</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Priorities</option>
          </select>
          <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
            <Filter size={14} />
            Filters
          </button>
        </div>

        {/* Notifications Table */}
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  <th className="px-4 py-3 text-[10px] text-gray-500 uppercase font-medium">Notification</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium text-right">Time</th>
                </tr>
              </thead>
              <tbody>
                {notificationRows.map((row) => {
                  const IconComponent = row.icon;
                  return (
                    <tr key={row.id} className="border-b border-white/[0.05] hover:bg-white/[0.02]">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          <div className={`w-9 h-9 rounded-full ${row.iconBg} flex items-center justify-center flex-shrink-0`}>
                            <IconComponent size={16} className={row.iconColor} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="text-xs text-white font-medium">{row.title}</p>
                            <p className="text-[10px] text-gray-500 mt-0.5">{row.description}</p>
                            <div className="flex items-center gap-2 mt-1">
                              <span className={`text-[10px] px-2 py-0.5 rounded ${row.moduleBadgeColor}`}>
                                {row.module}
                              </span>
                              <span className="flex items-center gap-1 text-[10px] text-gray-500">
                                <span className={`w-1.5 h-1.5 rounded-full ${row.priorityColor}`} />
                                {row.priority}
                              </span>
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-right align-top">
                        <div className="flex items-center justify-end gap-2">
                          <span className="text-[10px] text-gray-500">{row.time}</span>
                          <button className="text-gray-500 hover:text-gray-300">
                            <MoreHorizontal size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 flex items-center justify-between border-t border-white/[0.05]">
            <span className="text-[10px] text-gray-500">Showing 1 to 12 of 148 notifications</span>
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded bg-indigo-500/20 text-indigo-400 text-[10px]">1</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <span className="text-[10px] text-gray-500 px-1">...</span>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">13</button>
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
        {/* Notification Summary */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Notification Summary</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">Last 7 days</span>
          </div>
          <div className="h-44 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={summaryChartData}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={65}
                  dataKey="value"
                  stroke="none"
                >
                  {summaryChartData.map((entry) => (
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
                <p className="text-lg font-bold text-white">148</p>
                <p className="text-[9px] text-gray-500">Total</p>
              </div>
            </div>
          </div>
          <div className="space-y-1.5 mt-3">
            {summaryChartData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-[10px] text-gray-400">{item.name}</span>
                </div>
                <span className="text-[10px] text-gray-500">
                  {item.value} ({item.percentage})
                </span>
              </div>
            ))}
          </div>
        </Card>

        {/* Priority Breakdown */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Priority Breakdown</h3>
            <span className="text-[10px] text-red-400 cursor-pointer">Last 7 days</span>
          </div>
          <div className="space-y-3">
            {priorityBreakdown.map((item) => (
              <div key={item.label} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className={`w-6 h-6 rounded ${item.bgColor} flex items-center justify-center`}>
                    {item.icon === 'up' ? (
                      <AlertTriangle size={12} className={item.color} />
                    ) : (
                      <ArrowDown size={12} className={item.color} />
                    )}
                  </div>
                  <span className="text-xs text-gray-300">{item.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-white font-medium">{item.count}</span>
                  <span className="text-[10px] text-gray-500">{item.percentage}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Recent Unread */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Recent Unread</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">Mark all as read</span>
          </div>
          <div className="space-y-3">
            {recentUnread.map((item, idx) => (
              <div key={idx} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className={`w-2 h-2 rounded-full ${item.dotColor}`} />
                  <span className="text-xs text-gray-300">{item.title}</span>
                </div>
                <span className="text-[10px] text-gray-500">{item.time}</span>
              </div>
            ))}
          </div>
          <button className="text-[10px] text-indigo-400 mt-4 hover:text-indigo-300 transition-colors">
            View all unread (8)
          </button>
        </Card>

        {/* Notification Preferences */}
        <Card padding="lg">
          <h3 className="text-white font-semibold text-sm mb-4">Notification Preferences</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-300">Email Notifications</span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-green-400">Enabled</span>
                <ChevronRight size={12} className="text-gray-500" />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-300">Push Notifications</span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-green-400">Enabled</span>
                <ChevronRight size={12} className="text-gray-500" />
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-300">Slack Notifications</span>
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-red-400">Disabled</span>
                <ChevronRight size={12} className="text-gray-500" />
              </div>
            </div>
            <div className="pt-2 border-t border-white/[0.05]">
              <button className="text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors">
                Manage Preferences
              </button>
            </div>
          </div>
        </Card>

        {/* Quiet Hours */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-semibold text-sm">Quiet Hours</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">Edit</span>
          </div>
          <p className="text-xs text-gray-300">10:00 PM – 7:00 AM (Daily)</p>
          <p className="text-[10px] text-gray-500 mt-1">You won't receive non-urgent notifications</p>
        </Card>
      </div>
    </div>
  );
}
