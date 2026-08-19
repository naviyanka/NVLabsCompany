import { Card } from '@/components/common/Card';
import {
  GitBranch,
  Folder,
  Activity,
  GitCommit,
  GitPullRequest,
  Eye,
  CheckCircle2,
  Plus,
  Search,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Star,
  MoreVertical,
  List,
  LayoutGrid,
  ArrowUp,
  Lock,
  Globe,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

// ─── Static Mock Data ──────────────────────────────────────────────────────────

const statCards = [
  { label: 'Total Repositories', value: '18', change: '2 this week', icon: 'folder', iconBg: 'bg-pink-500/20', iconColor: 'text-pink-400' },
  { label: 'Active Repositories', value: '12', change: '3 this week', icon: 'activity', iconBg: 'bg-green-500/20', iconColor: 'text-green-400' },
  { label: 'Total Commits', value: '1,246', change: '18.5% vs last week', icon: 'commit', iconBg: 'bg-blue-500/20', iconColor: 'text-blue-400' },
  { label: 'Open Pull Requests', value: '24', change: '4 vs last week', icon: 'pr', iconBg: 'bg-teal-500/20', iconColor: 'text-teal-400' },
  { label: 'Code Reviews', value: '15', change: '7 vs last week', icon: 'eye', iconBg: 'bg-orange-500/20', iconColor: 'text-orange-400' },
  { label: 'Merge Success Rate', value: '96.3%', change: '2.4%', icon: 'check', iconBg: 'bg-purple-500/20', iconColor: 'text-purple-400' },
];

const pageTabs = ['All Repositories', 'My Repositories', 'Starred', 'Archived'];

const repositories = [
  {
    id: 1,
    name: 'NvLabsOrg/mission-control',
    visibility: 'Private',
    description: 'Main orchestration and dashboard application',
    language: 'TypeScript',
    langColor: '#3178c6',
    lastCommitMsg: 'feat(dashboard): add real-time agent metrics',
    lastCommitAuthor: 'Navi Yanka',
    lastCommitHash: 'a1b2c3d',
    status: 'Up to date',
    statusType: 'uptodate',
    updated: '2 minutes ago',
    starred: true,
  },
  {
    id: 2,
    name: 'NvLabsOrg/agent-core',
    visibility: 'Private',
    description: 'Core agent framework and runtime',
    language: 'Python',
    langColor: '#3572a5',
    lastCommitMsg: 'fix(memory): resolve vector store issue',
    lastCommitAuthor: 'Omega',
    lastCommitHash: 'd4e5f6g',
    status: 'Behind',
    statusType: 'behind',
    statusCount: 2,
    updated: '15 minutes ago',
    starred: true,
  },
  {
    id: 3,
    name: 'NvLabsOrg/pipelines',
    visibility: 'Private',
    description: 'Pipeline orchestration engine',
    language: 'Go',
    langColor: '#00add8',
    lastCommitMsg: 'feat(pipeline): add parallel execution',
    lastCommitAuthor: 'Vector',
    lastCommitHash: 'h7i8j9k',
    status: 'Up to date',
    statusType: 'uptodate',
    updated: '1 hour ago',
    starred: false,
  },
  {
    id: 4,
    name: 'NvLabsOrg/memory-service',
    visibility: 'Private',
    description: 'Memory and knowledge management',
    language: 'Python',
    langColor: '#3572a5',
    lastCommitMsg: 'chore: update embeddings model',
    lastCommitAuthor: 'MemoryX',
    lastCommitHash: 'l1m2n3o',
    status: 'Ahead',
    statusType: 'ahead',
    statusCount: 3,
    updated: '2 hours ago',
    starred: true,
  },
  {
    id: 5,
    name: 'NvLabsOrg/ui-components',
    visibility: 'Private',
    description: 'Reusable UI components library',
    language: 'TypeScript',
    langColor: '#3178c6',
    lastCommitMsg: 'feat(ui): new data table component',
    lastCommitAuthor: 'Navi Yanka',
    lastCommitHash: 'p4q5r6s',
    status: 'Up to date',
    statusType: 'uptodate',
    updated: '3 hours ago',
    starred: false,
  },
  {
    id: 6,
    name: 'NvLabsOrg/docs',
    visibility: 'Public',
    description: 'Documentation and guides',
    language: 'Markdown',
    langColor: '#083fa1',
    lastCommitMsg: 'docs: update HR room guide',
    lastCommitAuthor: 'Pulse',
    lastCommitHash: 't7u8v9w',
    status: 'Up to date',
    statusType: 'uptodate',
    updated: '5 hours ago',
    starred: false,
  },
  {
    id: 7,
    name: 'NvLabsOrg/infrastructure',
    visibility: 'Private',
    description: 'Infrastructure as Code',
    language: 'Terraform',
    langColor: '#5c4ee5',
    lastCommitMsg: 'chore(terraform): optimize resources',
    lastCommitAuthor: 'Shield',
    lastCommitHash: 'x1y2z3a',
    status: 'Behind',
    statusType: 'behind',
    statusCount: 1,
    updated: '1 day ago',
    starred: false,
  },
  {
    id: 8,
    name: 'NvLabsOrg/ai-models',
    visibility: 'Private',
    description: 'AI models and training scripts',
    language: 'Python',
    langColor: '#3572a5',
    lastCommitMsg: 'feat(model): add new fine-tuning script',
    lastCommitAuthor: 'Quill',
    lastCommitHash: 'b4c5d6e',
    status: 'Up to date',
    statusType: 'uptodate',
    updated: '2 days ago',
    starred: true,
  },
];

const commitActivityData = [
  { date: 'May 10', commits: 220 },
  { date: 'May 11', commits: 280 },
  { date: 'May 12', commits: 350 },
  { date: 'May 13', commits: 310 },
  { date: 'May 14', commits: 260 },
  { date: 'May 15', commits: 340 },
  { date: 'May 16', commits: 290 },
];

const prDonutData = [
  { name: 'Open', value: 9, percent: '37.5%', color: '#3b82f6' },
  { name: 'In Review', value: 7, percent: '29.2%', color: '#f59e0b' },
  { name: 'Approved', value: 5, percent: '20.8%', color: '#10b981' },
  { name: 'Draft', value: 3, percent: '12.5%', color: '#6b7280' },
];

const mergeTrendsData = [
  { date: 'May 10', merged: 22, closed: 4 },
  { date: 'May 11', merged: 28, closed: 6 },
  { date: 'May 12', merged: 35, closed: 3 },
  { date: 'May 13', merged: 30, closed: 5 },
  { date: 'May 14', merged: 25, closed: 7 },
  { date: 'May 15', merged: 32, closed: 4 },
  { date: 'May 16', merged: 28, closed: 2 },
];

const activityFeed = [
  { text: 'Navi Yanka pushed to mission-control', time: '2m ago' },
  { text: 'Omega created a pull request in agent-core', time: '15m ago' },
  { text: 'Vector merged PR #128 in pipelines', time: '45m ago' },
  { text: 'MemoryX pushed to memory-service', time: '1h ago' },
  { text: 'Pulse commented on PR #127 in ui-components', time: '2h ago' },
  { text: 'Shield created branch feature/optimize-db', time: '3h ago' },
  { text: 'Quill opened an issue in ai-models', time: '5h ago' },
];

const topContributors = [
  { name: 'Navi Yanka', commits: 124, change: 15 },
  { name: 'Omega', commits: 98, change: 8 },
  { name: 'Vector', commits: 87, change: 12 },
  { name: 'MemoryX', commits: 76, change: 5 },
  { name: 'Shield', commits: 65, change: 7 },
];

const languageDistData = [
  { name: 'TypeScript', value: 6, percent: '33.3%', color: '#3b82f6' },
  { name: 'Python', value: 5, percent: '27.8%', color: '#10b981' },
  { name: 'Go', value: 2, percent: '11.1%', color: '#06b6d4' },
  { name: 'Terraform', value: 2, percent: '11.1%', color: '#8b5cf6' },
  { name: 'Markdown', value: 2, percent: '11.1%', color: '#f59e0b' },
  { name: 'Other', value: 1, percent: '5.6%', color: '#6b7280' },
];

// ─── Helper Components ─────────────────────────────────────────────────────────

function StatCardIcon({ type, className }: { type: string; className: string }) {
  switch (type) {
    case 'folder':
      return <Folder size={20} className={className} />;
    case 'activity':
      return <Activity size={20} className={className} />;
    case 'commit':
      return <GitCommit size={20} className={className} />;
    case 'pr':
      return <GitPullRequest size={20} className={className} />;
    case 'eye':
      return <Eye size={20} className={className} />;
    case 'check':
      return <CheckCircle2 size={20} className={className} />;
    default:
      return null;
  }
}

function RepoStatus({ statusType, statusCount }: { statusType: string; statusCount?: number }) {
  switch (statusType) {
    case 'uptodate':
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-green-400">
          <ArrowUp size={10} />
          Up to date
        </span>
      );
    case 'behind':
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-orange-400">
          <span className="w-1.5 h-1.5 rounded-full bg-orange-400" />
          Behind &darr;{statusCount}
        </span>
      );
    case 'ahead':
      return (
        <span className="inline-flex items-center gap-1 text-[10px] text-blue-400">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
          Ahead &uarr;{statusCount}
        </span>
      );
    default:
      return null;
  }
}

function CircularScore({ score, size = 80 }: { score: number; size?: number }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  return (
    <div className="relative" style={{ width: size, height: size }}>
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
        <div className="text-center">
          <span className="text-lg font-bold text-white">{score}</span>
          <span className="text-[10px] text-gray-400"> /100</span>
        </div>
      </div>
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function GitRepos() {
  return (
    <div className="flex gap-4">
      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <GitBranch size={24} className="text-indigo-400" />
              <h1 className="text-2xl font-bold text-white">Git Repositories</h1>
            </div>
            <p className="text-sm text-gray-400 mt-1">Manage all repositories, branches, and code changes</p>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] text-gray-300 text-sm rounded-lg hover:bg-dark-card transition-colors">
              Connect Repository
            </button>
            <button className="flex items-center gap-2 px-4 py-2 bg-[#10b981] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
              <Plus size={16} />
              New Repository
            </button>
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
                  <div className="flex items-center gap-1 mt-1">
                    <ArrowUp size={10} className="text-green-400" />
                    <span className="text-[10px] text-green-400">{stat.change}</span>
                  </div>
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
                  tab === 'All Repositories'
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
            <span className="text-sm text-gray-500">Search repositories...</span>
          </div>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Status</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Languages</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Visibility</option>
          </select>
          <div className="flex items-center gap-1 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400">
            <span>Sort: Recent Activity</span>
            <ChevronDown size={14} />
          </div>
          <div className="flex items-center border border-white/[0.08] rounded-lg overflow-hidden">
            <button className="p-2 bg-indigo-500/20 text-indigo-400">
              <List size={14} />
            </button>
            <button className="p-2 bg-dark-surface text-gray-400 hover:text-white transition-colors">
              <LayoutGrid size={14} />
            </button>
          </div>
        </div>

        {/* Repositories Table */}
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  <th className="px-4 py-3 text-[10px] text-gray-500 uppercase font-medium">Repository</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Language</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Last Commit</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Status</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Updated</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {repositories.map((repo) => (
                  <tr key={repo.id} className="border-b border-white/[0.05] hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div>
                          <div className="flex items-center gap-1.5">
                            <p className="text-xs text-white font-medium">{repo.name}</p>
                            <span className="inline-flex items-center gap-0.5 text-[9px] text-gray-500 border border-white/[0.08] rounded px-1 py-0.5">
                              {repo.visibility === 'Private' ? <Lock size={8} /> : <Globe size={8} />}
                              {repo.visibility}
                            </span>
                          </div>
                          <p className="text-[10px] text-gray-500 mt-0.5">{repo.description}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-1.5">
                        <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: repo.langColor }} />
                        <span className="text-xs text-gray-300">{repo.language}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <p className="text-[10px] text-gray-300 max-w-[200px] truncate">{repo.lastCommitMsg}</p>
                      <p className="text-[9px] text-gray-500 mt-0.5">
                        by {repo.lastCommitAuthor} ({repo.lastCommitHash})
                      </p>
                    </td>
                    <td className="px-3 py-3">
                      <RepoStatus statusType={repo.statusType} statusCount={repo.statusCount} />
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-[10px] text-gray-500">{repo.updated}</span>
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <Star
                          size={14}
                          className={repo.starred ? 'text-yellow-400 fill-yellow-400' : 'text-gray-500'}
                        />
                        <button className="text-gray-500 hover:text-gray-300">
                          <MoreVertical size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 flex items-center justify-between border-t border-white/[0.05]">
            <span className="text-[10px] text-gray-500">Showing 1 to 8 of 18 repositories</span>
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded bg-indigo-500/20 text-indigo-400 text-[10px]">1</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronRight size={12} />
              </button>
            </div>
            <select className="px-2 py-1 bg-dark-bg border border-white/[0.05] rounded text-[10px] text-gray-400 appearance-none">
              <option>10 / page</option>
            </select>
          </div>
        </Card>

        {/* Bottom Four-Column Section */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Column 1: Commit Activity */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Commit Activity</h3>
              <span className="text-[10px] text-gray-400 bg-dark-bg border border-white/[0.08] px-2 py-0.5 rounded">7 Days</span>
            </div>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={commitActivityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis
                    dataKey="date"
                    stroke="#6b7280"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="#6b7280"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                    domain={[0, 400]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1b2e',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      color: '#fff',
                      fontSize: '10px',
                    }}
                  />
                  <Bar dataKey="commits" fill="#8b5cf6" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>

          {/* Column 2: Pull Requests Donut */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Pull Requests</h3>
            </div>
            <div className="h-32 relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={prDonutData}
                    cx="50%"
                    cy="50%"
                    innerRadius={35}
                    outerRadius={55}
                    dataKey="value"
                    stroke="none"
                  >
                    {prDonutData.map((entry) => (
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
                  <p className="text-lg font-bold text-white">24</p>
                  <p className="text-[9px] text-gray-500">Total</p>
                </div>
              </div>
            </div>
            <div className="space-y-1.5 mt-3">
              {prDonutData.map((item) => (
                <div key={item.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-1.5">
                    <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-[10px] text-gray-400">{item.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500">
                    {item.value} ({item.percent})
                  </span>
                </div>
              ))}
            </div>
          </Card>

          {/* Column 3: Merge Trends */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Merge Trends</h3>
              <span className="text-[10px] text-gray-400 bg-dark-bg border border-white/[0.08] px-2 py-0.5 rounded">7 Days</span>
            </div>
            <div className="h-40">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={mergeTrendsData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
                  <XAxis
                    dataKey="date"
                    stroke="#6b7280"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                  />
                  <YAxis
                    stroke="#6b7280"
                    fontSize={9}
                    tickLine={false}
                    axisLine={false}
                    domain={[0, 40]}
                  />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1b2e',
                      border: '1px solid rgba(255,255,255,0.08)',
                      borderRadius: '8px',
                      color: '#fff',
                      fontSize: '10px',
                    }}
                  />
                  <Line type="monotone" dataKey="merged" stroke="#10b981" strokeWidth={2} dot={false} name="Merged" />
                  <Line type="monotone" dataKey="closed" stroke="#ef4444" strokeWidth={2} dot={false} name="Closed" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="flex items-center gap-4 mt-2">
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-green-500" />
                <span className="text-[10px] text-gray-400">Merged</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-red-500" />
                <span className="text-[10px] text-gray-400">Closed</span>
              </div>
            </div>
          </Card>

          {/* Column 4: Code Health */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Code Health</h3>
            </div>
            <div className="flex justify-center mb-4">
              <CircularScore score={92} size={80} />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                  <span className="text-[10px] text-gray-400">Test Coverage</span>
                </div>
                <span className="text-[10px] text-white font-medium">89%</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                  <span className="text-[10px] text-gray-400">Code Quality</span>
                </div>
                <span className="text-[10px] text-white font-medium">A</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                  <span className="text-[10px] text-gray-400">Security Score</span>
                </div>
                <span className="text-[10px] text-white font-medium">94%</span>
              </div>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-green-400" />
                  <span className="text-[10px] text-gray-400">Maintainability</span>
                </div>
                <span className="text-[10px] text-white font-medium">A</span>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Right Sidebar */}
      <div className="w-80 flex-shrink-0 space-y-4">
        {/* Repository Activity */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Repository Activity</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {activityFeed.map((item, idx) => (
              <div key={idx} className="flex items-start gap-3">
                <div className="w-1.5 h-1.5 rounded-full bg-indigo-400 mt-1.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-gray-300 leading-relaxed">{item.text}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5">{item.time}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Contributors */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Top Contributors (30d)</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {topContributors.map((contributor, idx) => (
              <div key={contributor.name} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-gray-500 w-4">{idx + 1}.</span>
                  <span className="text-xs text-white font-medium">{contributor.name}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-gray-400">{contributor.commits} commits</span>
                  <span className="text-[10px] text-green-400">&uarr; {contributor.change}%</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Language Distribution */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Language Distribution</h3>
          </div>
          <div className="h-32 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={languageDistData}
                  cx="50%"
                  cy="50%"
                  innerRadius={35}
                  outerRadius={55}
                  dataKey="value"
                  stroke="none"
                >
                  {languageDistData.map((entry) => (
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
                <p className="text-xs font-bold text-white">Total 18</p>
                <p className="text-[9px] text-gray-500">Repositories</p>
              </div>
            </div>
          </div>
          <div className="space-y-1.5 mt-3">
            {languageDistData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-[10px] text-gray-400">{item.name}</span>
                </div>
                <span className="text-[10px] text-gray-500">
                  {item.percent} ({item.value})
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
