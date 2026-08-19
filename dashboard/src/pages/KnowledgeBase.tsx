import { Card } from '@/components/common/Card';
import {
  BookOpen,
  FileText,
  FolderOpen,
  Eye,
  ThumbsUp,
  Sparkles,
  CheckCircle2,
  Search,
  Filter,
  Plus,
  ChevronLeft,
  ChevronRight,
  Star,
  MoreVertical,
  List,
  LayoutGrid,
  ArrowUp,
  ArrowRight,
  Upload,
  FileEdit,
  Settings,
  Bot,
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
  { label: 'Total Articles', value: '356', change: '18 this week', icon: 'file', iconBg: 'bg-pink-500/20', iconColor: 'text-pink-400' },
  { label: 'Categories', value: '24', change: '2 this week', icon: 'folder', iconBg: 'bg-green-500/20', iconColor: 'text-green-400' },
  { label: 'Total Views (30d)', value: '4,892', change: '12.4%', icon: 'eye', iconBg: 'bg-blue-500/20', iconColor: 'text-blue-400' },
  { label: 'Useful Votes', value: '1,245', change: '8.7%', icon: 'thumbsup', iconBg: 'bg-teal-500/20', iconColor: 'text-teal-400' },
  { label: 'AI References (30d)', value: '2,103', change: '15.6%', icon: 'sparkle', iconBg: 'bg-orange-500/20', iconColor: 'text-orange-400' },
  { label: 'Avg. Relevance Score', value: '92.6%', change: '', icon: 'check', iconBg: 'bg-purple-500/20', iconColor: 'text-purple-400', hasCircular: true },
];

const pageTabs = ['All Articles', 'My Articles', 'Bookmarked', 'Recently Updated', 'Drafts', 'Archived'];

const articles = [
  {
    id: 1,
    title: 'API Authentication Best Practices',
    description: 'Comprehensive guide to implementing secure authentication...',
    category: 'Security',
    categoryColor: 'bg-green-500/20 text-green-400',
    type: 'Guide',
    typeColor: 'bg-blue-500/20 text-blue-400',
    lastUpdated: 'May 16, 2024',
    author: 'Alpha',
    views: 342,
    relevance: 95,
    starred: false,
  },
  {
    id: 2,
    title: 'Database Optimization Strategies',
    description: 'Performance tuning techniques for various database systems...',
    category: 'Database',
    categoryColor: 'bg-purple-500/20 text-purple-400',
    type: 'Tutorial',
    typeColor: 'bg-orange-500/20 text-orange-400',
    lastUpdated: 'May 15, 2024',
    author: 'Omega',
    views: 289,
    relevance: 93,
    starred: false,
  },
  {
    id: 3,
    title: 'Bug Bounty Reconnaissance Guide',
    description: 'Step-by-step reconnaissance methodology for bug bounty hunters...',
    category: 'Security',
    categoryColor: 'bg-green-500/20 text-green-400',
    type: 'Guide',
    typeColor: 'bg-blue-500/20 text-blue-400',
    lastUpdated: 'May 14, 2024',
    author: 'Cipher',
    views: 567,
    relevance: 96,
    starred: true,
  },
  {
    id: 4,
    title: 'Microservices Architecture Patterns',
    description: 'Common patterns and best practices for microservices...',
    category: 'Architecture',
    categoryColor: 'bg-teal-500/20 text-teal-400',
    type: 'Reference',
    typeColor: 'bg-gray-500/20 text-gray-400',
    lastUpdated: 'May 14, 2024',
    author: 'Vector',
    views: 234,
    relevance: 91,
    starred: false,
  },
  {
    id: 5,
    title: 'API Rate Limiting Implementation',
    description: 'How to implement rate limiting in different frameworks...',
    category: 'Backend',
    categoryColor: 'bg-indigo-500/20 text-indigo-400',
    type: 'Tutorial',
    typeColor: 'bg-orange-500/20 text-orange-400',
    lastUpdated: 'May 13, 2024',
    author: 'Nova',
    views: 198,
    relevance: 85,
    starred: false,
  },
  {
    id: 6,
    title: 'Incident Response Playbook',
    description: 'Complete incident response process and procedures...',
    category: 'Operations',
    categoryColor: 'bg-red-500/20 text-red-400',
    type: 'Playbook',
    typeColor: 'bg-pink-500/20 text-pink-400',
    lastUpdated: 'May 12, 2024',
    author: 'Shield',
    views: 445,
    relevance: 94,
    starred: false,
  },
];

const knowledgeCategories = [
  { name: 'Security', articles: 68, color: 'bg-red-400' },
  { name: 'Database', articles: 52, color: 'bg-purple-400' },
  { name: 'Backend', articles: 48, color: 'bg-indigo-400' },
  { name: 'Architecture', articles: 42, color: 'bg-teal-400' },
  { name: 'DevOps', articles: 38, color: 'bg-orange-400' },
  { name: 'Testing', articles: 31, color: 'bg-green-400' },
  { name: 'Others', articles: 77, color: 'bg-gray-400' },
];

const contentTypeData = [
  { name: 'Guide', value: 116, percent: '32.6%', color: '#10b981' },
  { name: 'Tutorial', value: 100, percent: '28.1%', color: '#f59e0b' },
  { name: 'Reference', value: 69, percent: '19.4%', color: '#3b82f6' },
  { name: 'Playbook', value: 39, percent: '11.0%', color: '#ec4899' },
  { name: 'Documentation', value: 32, percent: '8.9%', color: '#14b8a6' },
];

const aiUsageInsights = [
  { label: 'Articles Referenced by AI', value: '2,103', change: '15.6%' },
  { label: 'Successful Answers Generated', value: '1,892', change: '12.3%' },
  { label: 'Average Relevance Score', value: '92.6%', change: '3.2%' },
  { label: 'Knowledge Gaps Identified', value: '23', change: '4.6%' },
];

const recentActivity = [
  { text: 'Alpha updated API Authentication Best Practices', time: '2m ago' },
  { text: 'Omega created Database Indexing Guide', time: '15m ago' },
  { text: 'Vector bookmarked Microservices Architecture Patterns', time: '1h ago' },
  { text: 'Cipher added to favorites Bug Bounty Recon Guide', time: '2h ago' },
  { text: 'Shield commented on Incident Response Playbook', time: '3h ago' },
  { text: 'Quill updated API Rate Limiting Implementation', time: '5h ago' },
];

const popularArticles = [
  { title: 'Bug Bounty Reconnaissance Guide', views: 567 },
  { title: 'API Authentication Best Practices', views: 342 },
  { title: 'Incident Response Playbook', views: 445 },
  { title: 'Database Optimization Strategies', views: 289 },
  { title: 'Microservices Architecture Patterns', views: 234 },
];

const quickActions = [
  { label: 'Create New Article', icon: 'plus' },
  { label: 'Upload Documents', icon: 'upload' },
  { label: 'Create from Template', icon: 'template' },
  { label: 'AI Generate Article', icon: 'sparkle' },
  { label: 'Manage Categories', icon: 'settings' },
];

// ─── Helper Components ─────────────────────────────────────────────────────────

function StatCardIcon({ type, className }: { type: string; className: string }) {
  switch (type) {
    case 'file':
      return <FileText size={20} className={className} />;
    case 'folder':
      return <FolderOpen size={20} className={className} />;
    case 'eye':
      return <Eye size={20} className={className} />;
    case 'thumbsup':
      return <ThumbsUp size={20} className={className} />;
    case 'sparkle':
      return <Sparkles size={20} className={className} />;
    case 'check':
      return <CheckCircle2 size={20} className={className} />;
    default:
      return null;
  }
}

function QuickActionIcon({ type, className }: { type: string; className: string }) {
  switch (type) {
    case 'plus':
      return <Plus size={14} className={className} />;
    case 'upload':
      return <Upload size={14} className={className} />;
    case 'template':
      return <FileEdit size={14} className={className} />;
    case 'sparkle':
      return <Sparkles size={14} className={className} />;
    case 'settings':
      return <Settings size={14} className={className} />;
    default:
      return null;
  }
}

function CircularProgress({ percent, size = 36 }: { percent: number; size?: number }) {
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
        stroke="#8b5cf6"
        strokeWidth="3"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
      />
    </svg>
  );
}

function RelevanceBar({ value }: { value: number }) {
  const barColor = value >= 90 ? 'bg-green-400' : value >= 80 ? 'bg-yellow-400' : 'bg-orange-400';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${barColor}`}
          style={{ width: `${value}%` }}
        />
      </div>
      <span className="text-[10px] text-gray-400">{value}%</span>
    </div>
  );
}

// ─── Main Component ────────────────────────────────────────────────────────────

export function KnowledgeBase() {
  return (
    <div className="flex gap-4">
      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <BookOpen size={24} className="text-indigo-400" />
              <h1 className="text-2xl font-bold text-white">Knowledge Base</h1>
            </div>
            <p className="text-sm text-gray-400 mt-1">Centralized knowledge hub for agents, teams, and systems</p>
          </div>
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-teal-500/50 text-teal-400 text-sm rounded-lg hover:bg-teal-500/10 transition-colors">
              <Bot size={14} />
              AI Assistant
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] text-gray-300 text-sm rounded-lg hover:bg-dark-card transition-colors">
              <Upload size={14} />
              Import Docs
            </button>
            <button className="flex items-center gap-2 px-4 py-2 bg-[#10b981] text-white text-sm font-medium rounded-lg hover:opacity-90 transition-opacity">
              <Plus size={16} />
              New Article
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
                  {stat.change && (
                    <div className="flex items-center gap-1 mt-1">
                      <ArrowUp size={10} className="text-green-400" />
                      <span className="text-[10px] text-green-400">{stat.change}</span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {stat.hasCircular && (
                    <CircularProgress percent={92.6} />
                  )}
                  {!stat.hasCircular && (
                    <div className={`w-10 h-10 ${stat.iconBg} rounded-lg flex items-center justify-center`}>
                      <StatCardIcon type={stat.icon} className={stat.iconColor} />
                    </div>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg">
            <Search size={14} className="text-gray-500" />
            <input type="text" placeholder="Search articles, topics, or keywords..." className="text-sm text-gray-500 bg-transparent outline-none flex-1" />
          </div>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Categories</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Tags</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Agents</option>
          </select>
          <select className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8">
            <option>All Types</option>
          </select>
          <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
            <Filter size={14} />
            Filters
          </button>
          <div className="flex items-center border border-white/[0.08] rounded-lg overflow-hidden">
            <button className="p-2 bg-indigo-500/20 text-indigo-400">
              <List size={14} />
            </button>
            <button className="p-2 bg-dark-surface text-gray-400 hover:text-white transition-colors">
              <LayoutGrid size={14} />
            </button>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-white/[0.08]">
          <div className="flex items-center gap-1">
            {pageTabs.map((tab) => (
              <button
                key={tab}
                className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                  tab === 'All Articles'
                    ? 'text-indigo-400 border-b-2 border-indigo-400'
                    : 'text-gray-400 hover:text-gray-300'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        {/* Articles Table */}
        <Card padding="none">
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-white/[0.05]">
                  <th className="px-4 py-3 text-[10px] text-gray-500 uppercase font-medium">Article</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Category</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Type</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Last Updated</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Views</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Relevance</th>
                  <th className="px-3 py-3 text-[10px] text-gray-500 uppercase font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {articles.map((article) => (
                  <tr key={article.id} className="border-b border-white/[0.05] hover:bg-white/[0.02]">
                    <td className="px-4 py-3">
                      <p className="text-xs text-white font-medium">{article.title}</p>
                      <p className="text-[10px] text-gray-500 mt-0.5">{article.description}</p>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`text-[10px] px-2 py-1 rounded ${article.categoryColor}`}>
                        {article.category}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`text-[10px] px-2 py-1 rounded ${article.typeColor}`}>
                        {article.type}
                      </span>
                    </td>
                    <td className="px-3 py-3">
                      <p className="text-[10px] text-gray-300">{article.lastUpdated}</p>
                      <p className="text-[9px] text-gray-500 mt-0.5">by {article.author}</p>
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-xs text-gray-300">{article.views}</span>
                    </td>
                    <td className="px-3 py-3">
                      <RelevanceBar value={article.relevance} />
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <Star
                          size={14}
                          className={article.starred ? 'text-yellow-400 fill-yellow-400' : 'text-gray-500'}
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
            <span className="text-[10px] text-gray-500">Showing 1 to 6 of 356 articles</span>
            <div className="flex items-center gap-1">
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05]">
                <ChevronLeft size={12} />
              </button>
              <button className="w-7 h-7 flex items-center justify-center rounded bg-indigo-500/20 text-indigo-400 text-[10px]">1</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">2</button>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">3</button>
              <span className="text-[10px] text-gray-500 px-1">...</span>
              <button className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] text-[10px]">60</button>
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
          {/* Column 1: Knowledge Categories */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Knowledge Categories</h3>
              <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
            </div>
            <div className="space-y-3">
              {knowledgeCategories.map((cat) => (
                <div key={cat.name} className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${cat.color}`} />
                    <span className="text-xs text-gray-300">{cat.name}</span>
                  </div>
                  <span className="text-[10px] text-gray-500">{cat.articles} articles</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Column 2: Content Types Distribution - Donut Chart */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Content Types Distribution</h3>
            </div>
            <div className="h-40 relative">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={contentTypeData}
                    cx="50%"
                    cy="50%"
                    innerRadius={40}
                    outerRadius={60}
                    dataKey="value"
                    stroke="none"
                  >
                    {contentTypeData.map((entry) => (
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
              {contentTypeData.map((item) => (
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

          {/* Column 3: AI Usage Insights */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">AI Usage Insights (30d)</h3>
            </div>
            <div className="space-y-4">
              {aiUsageInsights.map((item) => (
                <div key={item.label}>
                  <p className="text-[10px] text-gray-400">{item.label}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-sm font-semibold text-white">{item.value}</span>
                    <div className="flex items-center gap-0.5">
                      <ArrowUp size={10} className="text-green-400" />
                      <span className="text-[10px] text-green-400">{item.change}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 pt-3 border-t border-white/[0.05]">
              <button className="flex items-center gap-1 text-xs text-indigo-400 hover:text-indigo-300 transition-colors">
                View AI Analytics
                <ArrowRight size={12} />
              </button>
            </div>
          </Card>
        </div>
      </div>

      {/* Right Sidebar */}
      <div className="w-80 flex-shrink-0 space-y-4">
        {/* Recent Activity */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Recent Activity</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {recentActivity.map((item, idx) => (
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

        {/* Popular Articles */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Popular Articles</h3>
            <span className="text-[10px] text-indigo-400 cursor-pointer">View All</span>
          </div>
          <div className="space-y-3">
            {popularArticles.map((article, idx) => (
              <div key={article.title} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-gray-500 w-4">{idx + 1}.</span>
                  <span className="text-xs text-white font-medium">{article.title}</span>
                </div>
                <span className="text-[10px] text-gray-500 flex-shrink-0 ml-2">{article.views} views</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Quick Actions */}
        <Card padding="lg">
          <div className="mb-4">
            <h3 className="text-white font-semibold text-sm">Quick Actions</h3>
          </div>
          <div className="space-y-2">
            {quickActions.map((action) => (
              <button
                key={action.label}
                className="w-full flex items-center gap-3 px-3 py-2.5 bg-dark-bg border border-white/[0.05] rounded-lg text-xs text-gray-300 hover:border-white/[0.12] transition-colors"
              >
                <QuickActionIcon type={action.icon} className="text-gray-400" />
                {action.label}
              </button>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
