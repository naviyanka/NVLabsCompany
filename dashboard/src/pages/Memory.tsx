import { Card } from '@/components/common/Card';
import {
  Brain,
  Users,
  Database,
  CheckCircle2,
  MessageSquare,
  RefreshCw,
  Search,
  Filter,
  Plus,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Star,
  MoreVertical,
  X,
  Copy,
  Pencil,
  Link2,
  Share2,
  Archive,
  Trash2,
  ArrowUp,
} from 'lucide-react';
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
} from 'recharts';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const statCards = [
  { label: 'Total Memories', value: '245.6K', change: '18.4K this week', changeUp: true, icon: 'brain', iconBg: 'bg-purple-500/20', iconColor: 'text-purple-400' },
  { label: 'Agents with Memory', value: '28 /32', change: '4 this week', changeUp: true, icon: 'users', iconBg: 'bg-blue-500/20', iconColor: 'text-blue-400' },
  { label: 'Memory Size', value: '48.7 GB', change: '6.2 GB this week', changeUp: true, icon: 'database', iconBg: 'bg-green-500/20', iconColor: 'text-green-400' },
  { label: 'Avg. Relevance Score', value: '92.4%', change: '4.3%', changeUp: true, icon: 'check', iconBg: 'bg-teal-500/20', iconColor: 'text-teal-400' },
  { label: 'Top Memory Source', value: 'Conversations', change: '', changeUp: false, icon: 'message', iconBg: 'bg-orange-500/20', iconColor: 'text-orange-400' },
  { label: 'Retention (30d)', value: '98.1%', change: '', changeUp: false, icon: 'refresh', iconBg: 'bg-indigo-500/20', iconColor: 'text-indigo-400' },
];

const pageTabs = ['Overview', 'Agent Memories', 'Shared Knowledge', 'Conversations', 'Embeddings', 'Settings'];

const memorySourcesData = [
  { name: 'Conversations', value: 110500, percent: 45, color: '#3b82f6' },
  { name: 'Tasks & Results', value: 61400, percent: 25, color: '#10b981' },
  { name: 'Code Repos', value: 39900, percent: 15, color: '#f59e0b' },
  { name: 'Web & Docs', value: 24800, percent: 10, color: '#8b5cf6' },
  { name: 'Manual Entries', value: 12200, percent: 5, color: '#6b7280' },
];

const topAgents = [
  { name: 'Alpha', role: 'Backend Developer', count: '24.5K' },
  { name: 'Nova', role: 'Security Analyst', count: '21.8K' },
  { name: 'Omega', role: 'Research Specialist', count: '19.6K' },
  { name: 'Cipher', role: 'Bug Bounty Hunter', count: '17.2K' },
  { name: 'Vector', role: 'Data Engineer', count: '16.4K' },
];

const memoryHealth = [
  { label: 'Duplicate Memories', count: '1.2K', action: 'Review', actionColor: 'text-red-400 border-red-500/30 bg-red-500/10' },
  { label: 'Low Relevance', count: '842', action: 'Review', actionColor: 'text-red-400 border-red-500/30 bg-red-500/10' },
  { label: 'Stale Memories (90d+)', count: '2.4K', action: 'Archive', actionColor: 'text-orange-400 border-orange-500/30 bg-orange-500/10' },
  { label: 'Unlinked Entities', count: '653', action: 'Review', actionColor: 'text-red-400 border-red-500/30 bg-red-500/10' },
];

const memorySubTabs = ['Recent Memories', 'Important', 'Starred', 'Low Relevance'];

const memoryEntries = [
  {
    id: 1,
    title: 'Subdomain enumeration best practices',
    description: 'Use assetfinder, subfinder and amass in combination for comprehensive subdomain discovery...',
    tags: ['Alpha', 'Subdomain Enumeration', 'Recon'],
    priority: 'High',
    priorityColor: 'text-green-400',
    date: 'May 16, 10:21 AM',
    starred: true,
  },
  {
    id: 2,
    title: 'JWT authentication bypass techniques',
    description: 'Common mistakes in JWT implementation and how to test for algorithm confusion, weak secrets...',
    tags: ['Nova', 'JWT', 'Authentication'],
    priority: 'High',
    priorityColor: 'text-green-400',
    date: 'May 16, 09:45 AM',
    starred: false,
  },
  {
    id: 3,
    title: 'Bug bounty writeup template v2',
    description: 'Updated template for bug bounty reports with impact, steps to reproduce, and remediation...',
    tags: ['Omega', 'Reporting', 'Template'],
    priority: 'Medium',
    priorityColor: 'text-yellow-400',
    date: 'May 16, 09:30 AM',
    starred: true,
  },
  {
    id: 4,
    title: 'SQL injection payload list',
    description: 'Comprehensive list of SQL payloads for different DBMS with bypass techniques...',
    tags: ['Cipher', 'SQL Injection', 'Exploitation'],
    priority: 'High',
    priorityColor: 'text-green-400',
    date: 'May 16, 09:10 AM',
    starred: false,
  },
  {
    id: 5,
    title: 'Docker security checklist',
    description: 'Essential security checks for Docker containers, images and docker-compose configurations...',
    tags: ['Vector', 'Docker', 'Security'],
    priority: 'Medium',
    priorityColor: 'text-yellow-400',
    date: 'May 16, 08:55 AM',
    starred: false,
  },
  {
    id: 6,
    title: 'Rate limiting bypass methods',
    description: 'Techniques to identify and bypass rate limiting mechanisms in APIs and web applications...',
    tags: ['Pulse', 'Rate Limiting', 'API Security'],
    priority: 'Medium',
    priorityColor: 'text-yellow-400',
    date: 'May 16, 08:30 AM',
    starred: false,
  },
  {
    id: 7,
    title: 'API endpoint discovery tools',
    description: 'List of tools and methods for discovering hidden API endpoints in web applications...',
    tags: ['Shadow', 'API Discovery', 'Recon'],
    priority: 'Low',
    priorityColor: 'text-gray-400',
    date: 'May 16, 08:15 AM',
    starred: false,
  },
];

const relevanceBreakdown = [
  { label: 'Accuracy', value: 96 },
  { label: 'Completeness', value: 92 },
  { label: 'Recency', value: 88 },
  { label: 'Relevance', value: 98 },
];

const detailTabs = ['Details', 'Links', 'Embeddings', 'History'];

// ─── Helper Components ─────────────────────────────────────────────────────────

function StatIcon({ type, className }: { type: string; className: string }) {
  switch (type) {
    case 'brain':
      return <Brain size={20} className={className} />;
    case 'users':
      return <Users size={20} className={className} />;
    case 'database':
      return <Database size={20} className={className} />;
    case 'check':
      return <CheckCircle2 size={20} className={className} />;
    case 'message':
      return <MessageSquare size={20} className={className} />;
    case 'refresh':
      return <RefreshCw size={20} className={className} />;
    default:
      return null;
  }
}

function RelevanceCircle({ percent, size = 100 }: { percent: number; size?: number }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (percent / 100) * circumference;
  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="transform -rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="rgba(255,255,255,0.08)"
          strokeWidth="6"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#10b981"
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-xl font-bold text-white">{percent}%</span>
      </div>
    </div>
  );
}

function formatCount(value: number): string {
  if (value >= 1000) {
    return `${(value / 1000).toFixed(1)}K`;
  }
  return value.toString();
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function Memory() {
  const activeTab = 'Overview';
  const activeSubTab = 'Recent Memories';
  const activeDetailTab = 'Details';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div>
        <div className="flex items-center gap-2">
          <Brain size={24} className="text-purple-400" />
          <h1 className="text-2xl font-bold text-white">Memory Center</h1>
        </div>
        <p className="text-sm text-gray-400 mt-1">Explore, search and manage knowledge across all agents</p>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-white/[0.08]">
        <div className="flex items-center gap-1">
          {pageTabs.map((tab) => (
            <button
              key={tab}
              className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                tab === activeTab
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
      <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-4">
        {statCards.map((stat) => (
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
              </div>
              <div className={`w-10 h-10 ${stat.iconBg} rounded-lg flex items-center justify-center`}>
                <StatIcon type={stat.icon} className={stat.iconColor} />
              </div>
            </div>
          </Card>
        ))}
      </div>

      {/* Search/Filter Bar */}
      <div className="flex items-center gap-3">
        <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg">
          <Search size={14} className="text-gray-500" />
          <input
            type="text"
            readOnly
            placeholder="Search memories..."
            className="flex-1 bg-transparent outline-none text-sm text-gray-500 placeholder-gray-500"
          />
        </div>
        <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
          <option>All Agents</option>
        </select>
        <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
          <option>All Types</option>
        </select>
        <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
          <option>All Sources</option>
        </select>
        <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
          <option>All Time</option>
        </select>
        <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
          <Filter size={14} />
          Filters
        </button>
        <button className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors">
          <Plus size={16} />
          Add Memory
        </button>
      </div>

      {/* Main Three-Column Layout */}
      <div className="flex flex-col lg:flex-row gap-4">
        {/* LEFT COLUMN */}
        <div className="w-full lg:w-[25%] lg:flex-shrink-0 space-y-4">
          {/* Memory Sources */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">Memory Sources</h3>
              <span className="text-[10px] text-teal-400 cursor-pointer">View All</span>
            </div>
            <div className="h-44 relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={memorySourcesData}
                    cx="50%"
                    cy="50%"
                    innerRadius={45}
                    outerRadius={65}
                    dataKey="value"
                    stroke="none"
                  >
                    {memorySourcesData.map((entry) => (
                      <Cell key={entry.name} fill={entry.color} />
                    ))}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
                <div className="text-center">
                  <p className="text-lg font-bold text-white">245.6K</p>
                  <p className="text-[9px] text-gray-500">Total</p>
                </div>
              </div>
            </div>
            <div className="space-y-2 mt-3">
              {memorySourcesData.map((item) => (
                <div key={item.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-[10px] text-gray-400">{item.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500">
                    {item.percent}% ({formatCount(item.value)})
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Top Agents by Memory */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">Top Agents by Memory</h3>
              <span className="text-[10px] text-teal-400 cursor-pointer">View All</span>
            </div>
            <div className="space-y-3">
              {topAgents.map((agent) => (
                <div key={agent.name} className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-white font-medium">{agent.name}</p>
                    <p className="text-[10px] text-gray-500">{agent.role}</p>
                  </div>
                  <span className="text-xs text-gray-400">{agent.count}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Memory Health */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-white font-semibold text-sm">Memory Health</h3>
              <span className="text-[10px] text-teal-400 cursor-pointer">View All</span>
            </div>
            <div className="space-y-3">
              {memoryHealth.map((item) => (
                <div key={item.label} className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-300">{item.label}</p>
                    <p className="text-[10px] text-gray-500">{item.count}</p>
                  </div>
                  <button className={`text-[10px] px-2 py-1 rounded border ${item.actionColor}`}>
                    {item.action}
                  </button>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* CENTER COLUMN */}
        <div className="flex-1 min-w-0 space-y-4">
          {/* Sub-tabs */}
          <div className="border-b border-white/[0.08]">
            <div className="flex items-center gap-1">
              {memorySubTabs.map((tab) => (
                <button
                  key={tab}
                  className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                    tab === activeSubTab
                      ? 'text-teal-400 border-b-2 border-teal-400'
                      : 'text-gray-400 hover:text-gray-300'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>
          </div>

          {/* Memory Entries */}
          <div className="space-y-3">
            {memoryEntries.map((entry) => (
              <Card key={entry.id} padding="md">
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <h4 className="text-sm text-white font-medium">{entry.title}</h4>
                    <p className="text-xs text-gray-400 mt-1 line-clamp-2">{entry.description}</p>
                    <div className="flex items-center gap-2 mt-2 flex-wrap">
                      {entry.tags.map((tag) => (
                        <span
                          key={tag}
                          className="text-[10px] px-2 py-0.5 rounded bg-white/[0.06] text-gray-300"
                        >
                          {tag}
                        </span>
                      ))}
                      <span className={`text-[10px] flex items-center gap-1 ${entry.priorityColor}`}>
                        <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: 'currentColor' }} />
                        {entry.priority}
                      </span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 ml-4 flex-shrink-0">
                    <span className="text-[10px] text-gray-500">{entry.date}</span>
                    {entry.starred && (
                      <Star size={12} className="text-yellow-400 fill-yellow-400" />
                    )}
                    <button className="text-gray-500 hover:text-gray-300">
                      <MoreVertical size={14} />
                    </button>
                  </div>
                </div>
              </Card>
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-gray-500">Showing 1 to 20 of 245,642 memories</span>
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded bg-teal-500/20 text-teal-400 text-[10px]">1</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">4</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">5</button>
              <span className="text-[10px] text-gray-500 px-1">...</span>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">12,283</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronRight size={12} />
              </button>
            </div>
            <div className="flex items-center gap-1">
              <select className="px-2 py-1 bg-dark-bg border border-white/[0.05] rounded text-[10px] text-gray-400 appearance-none">
                <option>20 / page</option>
              </select>
              <ChevronDown size={10} className="text-gray-500 -ml-4 pointer-events-none" />
            </div>
          </div>
        </div>

        {/* RIGHT COLUMN - Memory Details Sidebar */}
        <div className="w-full lg:w-[30%] lg:flex-shrink-0">
          <Card padding="none" className="sticky top-4">
            {/* Panel Header */}
            <div className="p-4 border-b border-white/[0.08]">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Memory Details</span>
                <button className="text-gray-500 hover:text-gray-300">
                  <X size={14} />
                </button>
              </div>
            </div>

            {/* Memory Title Section */}
            <div className="p-4 border-b border-white/[0.05]">
              <div className="flex items-center gap-2 mb-2">
                <h3 className="text-white font-semibold text-sm">Subdomain enumeration best practices</h3>
                <span className="text-[10px] bg-green-500/20 text-green-400 px-2 py-0.5 rounded">
                  High Relevance
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-gray-500">ID: mem_9f7a8c7d1e4b</span>
                <button className="text-gray-500 hover:text-gray-300">
                  <Copy size={10} />
                </button>
              </div>
            </div>

            {/* Detail Tabs */}
            <div className="px-4 border-b border-white/[0.05]">
              <div className="flex items-center gap-1">
                {detailTabs.map((tab) => (
                  <button
                    key={tab}
                    className={`px-3 py-2 text-[10px] font-medium whitespace-nowrap ${
                      tab === activeDetailTab
                        ? 'text-teal-400 border-b border-teal-400'
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
                Best practices for subdomain enumeration using various tools and techniques for comprehensive asset discovery.
              </p>
            </div>

            {/* Metadata Grid */}
            <div className="p-4 border-b border-white/[0.05]">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-[9px] text-gray-500 uppercase">Agent</p>
                  <p className="text-xs text-white mt-0.5">Alpha (Backend Developer)</p>
                </div>
                <div>
                  <p className="text-[9px] text-gray-500 uppercase">Source</p>
                  <p className="text-xs text-white mt-0.5">Agent Conversation</p>
                </div>
                <div>
                  <p className="text-[9px] text-gray-500 uppercase">Type</p>
                  <p className="text-xs text-white mt-0.5">Reconnaissance</p>
                </div>
                <div>
                  <p className="text-[9px] text-gray-500 uppercase">Created</p>
                  <p className="text-xs text-gray-300 mt-0.5">May 16, 2024, 10:21 AM</p>
                </div>
                <div>
                  <p className="text-[9px] text-gray-500 uppercase">Last Accessed</p>
                  <p className="text-xs text-gray-300 mt-0.5">May 16, 2024, 02:30 PM</p>
                </div>
                <div>
                  <p className="text-[9px] text-gray-500 uppercase">Access Count</p>
                  <p className="text-xs text-white mt-0.5">24</p>
                </div>
                <div className="col-span-2">
                  <p className="text-[9px] text-gray-500 uppercase mb-1">Tags</p>
                  <div className="flex items-center gap-1 flex-wrap">
                    {['Subdomain Enumeration', 'Recon', 'Best Practices', 'External Tools'].map((tag) => (
                      <span key={tag} className="text-[10px] px-2 py-0.5 rounded bg-white/[0.06] text-gray-300">
                        {tag}
                      </span>
                    ))}
                    <button className="text-[10px] text-teal-400 hover:text-teal-300">+ Add Tag</button>
                  </div>
                </div>
              </div>
            </div>

            {/* Relevance Score */}
            <div className="p-4 border-b border-white/[0.05]">
              <h4 className="text-[10px] text-gray-500 uppercase tracking-wide mb-3">Relevance Score</h4>
              <div className="flex items-center gap-4">
                <RelevanceCircle percent={94} size={100} />
                <div className="flex-1 space-y-2">
                  {relevanceBreakdown.map((item) => (
                    <div key={item.label}>
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[10px] text-gray-400">{item.label}</span>
                        <span className="text-[10px] text-gray-300">{item.value}%</span>
                      </div>
                      <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-green-500 rounded-full"
                          style={{ width: `${item.value}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="p-4">
              <h4 className="text-[10px] text-gray-500 uppercase tracking-wide mb-3">Actions</h4>
              <div className="grid grid-cols-2 gap-2">
                <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                  <Pencil size={12} />
                  Edit Memory
                </button>
                <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                  <Link2 size={12} />
                  Link to Task
                </button>
                <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                  <Share2 size={12} />
                  Share Memory
                </button>
                <button className="flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.05] rounded-lg text-[10px] text-gray-300 hover:border-white/[0.12] transition-colors">
                  <Archive size={12} />
                  Archive Memory
                </button>
                <button className="flex items-center gap-2 px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-[10px] text-red-400 hover:border-red-500/40 transition-colors col-span-2">
                  <Trash2 size={12} />
                  Delete Memory
                </button>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
