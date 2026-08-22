import { useState } from 'react';
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
  const [activeCategory, setActiveCategory] = useState('All');
  const [searchQuery, setSearchQuery] = useState('');
  const [notifications, setNotifications] = useState(notificationRows);
  const [readIds, setReadIds] = useState<Set<number>>(new Set());
  const [typeFilter, setTypeFilter] = useState('All Types');
  const [moduleFilter, setModuleFilter] = useState('All Modules');
  const [priorityFilter, setPriorityFilter] = useState('All Priorities');
  const [showSettingsModal, setShowSettingsModal] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  const [perPage, setPerPage] = useState(10);
  const [quietHoursEnabled, setQuietHoursEnabled] = useState(true);
  const [quietStart, setQuietStart] = useState('22:00');
  const [quietEnd, setQuietEnd] = useState('07:00');
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [pushEnabled, setPushEnabled] = useState(true);
  const [slackEnabled, setSlackEnabled] = useState(false);

  const filteredNotifications = notifications.filter((n) => {
    const matchesCategory =
      activeCategory === 'All' ||
      (activeCategory === 'Unread' && !readIds.has(n.id)) ||
      (activeCategory === 'Mentions' && n.module === 'Mentions') ||
      (activeCategory === 'Alerts' && n.priority === 'High') ||
      (activeCategory === 'System' && n.module === 'System');
    const matchesSearch = !searchQuery ||
      n.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      n.description.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesType = typeFilter === 'All Types' ||
      (typeFilter === 'Success' && n.priority === 'Success') ||
      (typeFilter === 'Warning' && n.priority === 'Medium') ||
      (typeFilter === 'Error' && n.priority === 'High') ||
      (typeFilter === 'Info' && n.priority === 'Low');
    const matchesModule = moduleFilter === 'All Modules' || n.module === moduleFilter;
    const matchesPriority = priorityFilter === 'All Priorities' || n.priority === priorityFilter;
    return matchesCategory && matchesSearch && matchesType && matchesModule && matchesPriority;
  });

  const totalPages = Math.ceil(filteredNotifications.length / perPage);
  const paginatedNotifications = filteredNotifications.slice((currentPage - 1) * perPage, currentPage * perPage);
  const unreadCount = notifications.filter((n) => !readIds.has(n.id)).length;

  const handleMarkAllRead = () => {
    setReadIds(new Set(notifications.map((n) => n.id)));
  };

  const handleMarkRead = (id: number) => {
    setReadIds((prev) => new Set([...prev, id]));
  };

  const handleDismiss = (id: number) => {
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  };

  const dynamicTabs = [
    { label: 'All', count: notifications.length },
    { label: 'Unread', count: unreadCount },
    { label: 'Mentions', count: notifications.filter((n) => n.module === 'Mentions').length },
    { label: 'Alerts', count: notifications.filter((n) => n.priority === 'High').length },
    { label: 'System', count: notifications.filter((n) => n.module === 'System').length },
  ];

  const uniqueModules = [...new Set(notifications.map((n) => n.module))];
  const uniquePriorities = [...new Set(notifications.map((n) => n.priority))];
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
            <button onClick={handleMarkAllRead} className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              Mark all as read
            </button>
            <button onClick={() => setShowSettingsModal(true)} className="flex items-center gap-2 px-3 py-2 bg-red-500/20 border border-red-500/30 rounded-lg text-sm text-red-400 hover:bg-red-500/30 transition-colors">
              <Settings size={14} />
              Notification Settings
            </button>
          </div>
        </div>

        {/* Category Tabs */}
        <div className="flex items-center gap-2">
          {dynamicTabs.map((tab) => (
            <button
              key={tab.label}
              onClick={() => setActiveCategory(tab.label)}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors ${
                activeCategory === tab.label
                  ? 'bg-blue-500/20 text-blue-400'
                  : 'bg-dark-surface border border-white/[0.08] text-gray-400 hover:text-white'
              }`}
            >
              {tab.label}
              <span className={`text-[10px] ${activeCategory === tab.label ? 'text-blue-400' : 'text-gray-500'}`}>
                {tab.count}
              </span>
            </button>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg">
            <Search size={14} className="text-gray-500" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search notifications..."
              className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 outline-none"
            />
          </div>
          <select value={typeFilter} onChange={(e) => { setTypeFilter(e.target.value); setCurrentPage(1); }} className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400">
            <option>All Types</option>
            <option>Success</option>
            <option>Warning</option>
            <option>Error</option>
            <option>Info</option>
          </select>
          <select value={moduleFilter} onChange={(e) => { setModuleFilter(e.target.value); setCurrentPage(1); }} className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400">
            <option>All Modules</option>
            {uniqueModules.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
          <select value={priorityFilter} onChange={(e) => { setPriorityFilter(e.target.value); setCurrentPage(1); }} className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400">
            <option>All Priorities</option>
            {uniquePriorities.map(p => <option key={p} value={p}>{p}</option>)}
          </select>
          <button onClick={() => { setTypeFilter('All Types'); setModuleFilter('All Modules'); setPriorityFilter('All Priorities'); setSearchQuery(''); setActiveCategory('All'); setCurrentPage(1); }} className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
            <Filter size={14} />
            Clear Filters
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
                {paginatedNotifications.map((row) => {
                  const IconComponent = row.icon;
                  const isRead = readIds.has(row.id);
                  return (
                    <tr key={row.id} className={`border-b border-white/[0.05] hover:bg-white/[0.02] ${isRead ? 'opacity-60' : ''}`}>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-3">
                          {!isRead && <span className="w-2 h-2 rounded-full bg-blue-400 flex-shrink-0" />}
                          {isRead && <span className="w-2 h-2 flex-shrink-0" />}
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
                          {!isRead && (
                            <button onClick={() => handleMarkRead(row.id)} className="text-[10px] text-blue-400 hover:text-blue-300" title="Mark as read">
                              ✓
                            </button>
                          )}
                          <button onClick={() => handleDismiss(row.id)} className="text-gray-500 hover:text-red-400" title="Dismiss">
                            <MoreHorizontal size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
                {filteredNotifications.length === 0 && (
                  <tr><td colSpan={2} className="px-4 py-8 text-center text-sm text-gray-500">No notifications match your filter</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 flex items-center justify-between border-t border-white/[0.05]">
            <span className="text-[10px] text-gray-500">Showing {((currentPage - 1) * perPage) + 1} to {Math.min(currentPage * perPage, filteredNotifications.length)} of {filteredNotifications.length} notifications</span>
            <div className="flex items-center gap-1">
              <button onClick={() => setCurrentPage(p => Math.max(1, p - 1))} disabled={currentPage === 1} className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] disabled:opacity-30">
                <ChevronLeft size={12} />
              </button>
              {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => i + 1).map(page => (
                <button key={page} onClick={() => setCurrentPage(page)} className={`w-7 h-7 flex items-center justify-center rounded text-[10px] ${currentPage === page ? 'bg-indigo-500/20 text-indigo-400' : 'text-gray-500 hover:bg-white/[0.05]'}`}>{page}</button>
              ))}
              {totalPages > 5 && <span className="text-[10px] text-gray-500 px-1">...</span>}
              <button onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} disabled={currentPage === totalPages || totalPages === 0} className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] disabled:opacity-30">
                <ChevronRight size={12} />
              </button>
            </div>
            <select value={perPage} onChange={(e) => { setPerPage(parseInt(e.target.value)); setCurrentPage(1); }} className="px-2 py-1 bg-dark-bg border border-white/[0.05] rounded text-[10px] text-gray-400">
              <option value={5}>5 / page</option>
              <option value={10}>10 / page</option>
              <option value={25}>25 / page</option>
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
            <span onClick={handleMarkAllRead} className="text-[10px] text-indigo-400 cursor-pointer">Mark all as read</span>
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
              <button onClick={() => setEmailEnabled(!emailEnabled)} className={`relative w-9 h-5 rounded-full transition-colors ${emailEnabled ? 'bg-green-500' : 'bg-gray-600'}`}>
                <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${emailEnabled ? 'left-[18px]' : 'left-0.5'}`} />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-300">Push Notifications</span>
              <button onClick={() => setPushEnabled(!pushEnabled)} className={`relative w-9 h-5 rounded-full transition-colors ${pushEnabled ? 'bg-green-500' : 'bg-gray-600'}`}>
                <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${pushEnabled ? 'left-[18px]' : 'left-0.5'}`} />
              </button>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-gray-300">Slack Notifications</span>
              <button onClick={() => setSlackEnabled(!slackEnabled)} className={`relative w-9 h-5 rounded-full transition-colors ${slackEnabled ? 'bg-green-500' : 'bg-gray-600'}`}>
                <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${slackEnabled ? 'left-[18px]' : 'left-0.5'}`} />
              </button>
            </div>
            <div className="pt-2 border-t border-white/[0.05]">
              <button onClick={() => setShowSettingsModal(true)} className="text-[10px] text-indigo-400 hover:text-indigo-300 transition-colors">
                Manage Preferences
              </button>
            </div>
          </div>
        </Card>

        {/* Quiet Hours */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-white font-semibold text-sm">Quiet Hours</h3>
            <button onClick={() => setQuietHoursEnabled(!quietHoursEnabled)} className={`relative w-9 h-5 rounded-full transition-colors ${quietHoursEnabled ? 'bg-indigo-500' : 'bg-gray-600'}`}>
              <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${quietHoursEnabled ? 'left-[18px]' : 'left-0.5'}`} />
            </button>
          </div>
          {quietHoursEnabled ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <input type="time" value={quietStart} onChange={(e) => setQuietStart(e.target.value)} className="bg-dark-bg border border-white/[0.08] rounded px-2 py-1 text-xs text-white" />
                <span className="text-xs text-gray-500">to</span>
                <input type="time" value={quietEnd} onChange={(e) => setQuietEnd(e.target.value)} className="bg-dark-bg border border-white/[0.08] rounded px-2 py-1 text-xs text-white" />
              </div>
              <p className="text-[10px] text-gray-500">Non-urgent notifications are silenced during these hours</p>
            </div>
          ) : (
            <p className="text-xs text-gray-500">Quiet hours are disabled. You'll receive all notifications.</p>
          )}
        </Card>
      </div>

      {/* Settings Modal */}
      {showSettingsModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-md mx-4 bg-[#0B1626] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/10">
              <h3 className="text-white font-semibold">Notification Settings</h3>
              <button onClick={() => setShowSettingsModal(false)} className="text-gray-400 hover:text-white text-lg">×</button>
            </div>
            <div className="p-5 space-y-4 max-h-[60vh] overflow-y-auto">
              <div className="space-y-3">
                <h4 className="text-xs text-gray-400 font-medium uppercase">Channels</h4>
                <ToggleRow label="Email Notifications" description="Receive alerts via email" enabled={emailEnabled} onToggle={() => setEmailEnabled(!emailEnabled)} />
                <ToggleRow label="Push Notifications" description="Browser push notifications" enabled={pushEnabled} onToggle={() => setPushEnabled(!pushEnabled)} />
                <ToggleRow label="Slack Integration" description="Forward notifications to Slack" enabled={slackEnabled} onToggle={() => setSlackEnabled(!slackEnabled)} />
              </div>
              <div className="space-y-3 pt-3 border-t border-white/[0.06]">
                <h4 className="text-xs text-gray-400 font-medium uppercase">Quiet Hours</h4>
                <ToggleRow label="Enable Quiet Hours" description="Silence non-urgent notifications" enabled={quietHoursEnabled} onToggle={() => setQuietHoursEnabled(!quietHoursEnabled)} />
                {quietHoursEnabled && (
                  <div className="flex items-center gap-2 pl-4">
                    <input type="time" value={quietStart} onChange={(e) => setQuietStart(e.target.value)} className="bg-dark-bg border border-white/[0.08] rounded px-2 py-1 text-xs text-white" />
                    <span className="text-xs text-gray-500">to</span>
                    <input type="time" value={quietEnd} onChange={(e) => setQuietEnd(e.target.value)} className="bg-dark-bg border border-white/[0.08] rounded px-2 py-1 text-xs text-white" />
                  </div>
                )}
              </div>
              <div className="space-y-3 pt-3 border-t border-white/[0.06]">
                <h4 className="text-xs text-gray-400 font-medium uppercase">Notification Types</h4>
                <ToggleRow label="Agent Completions" description="When agents finish tasks" enabled={true} onToggle={() => {}} />
                <ToggleRow label="Pipeline Failures" description="When pipelines fail" enabled={true} onToggle={() => {}} />
                <ToggleRow label="Security Alerts" description="Security scan results" enabled={true} onToggle={() => {}} />
                <ToggleRow label="System Updates" description="Deployments and maintenance" enabled={true} onToggle={() => {}} />
                <ToggleRow label="Mentions" description="When someone mentions you" enabled={true} onToggle={() => {}} />
              </div>
            </div>
            <div className="px-5 py-3 border-t border-white/[0.06] flex justify-end">
              <button onClick={() => setShowSettingsModal(false)} className="px-4 py-2 bg-indigo-500/20 text-indigo-400 text-sm font-medium rounded-lg hover:bg-indigo-500/30">
                Save Preferences
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ToggleRow({ label, description, enabled, onToggle }: { label: string; description: string; enabled: boolean; onToggle: () => void }) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <p className="text-xs text-white">{label}</p>
        <p className="text-[10px] text-gray-500">{description}</p>
      </div>
      <button onClick={onToggle} className={`relative w-9 h-5 rounded-full transition-colors ${enabled ? 'bg-green-500' : 'bg-gray-600'}`}>
        <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full transition-transform ${enabled ? 'left-[18px]' : 'left-0.5'}`} />
      </button>
    </div>
  );
}
