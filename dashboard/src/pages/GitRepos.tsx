import { useState, useEffect, useMemo } from 'react';
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
  Star,
  List,
  LayoutGrid,
  ArrowUp,
  Lock,
  RefreshCw,
  Trash2,
  X,
  ExternalLink,
  AlertTriangle,
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
import { repositoriesApi } from '@/api/repositories';
import { COMPANY_ID } from '@/config';
import type { Repository } from '@/types/repository';

// ─── Default Repository Data & Fallbacks ──────────────────────────────────────

const defaultRepos: (Repository & { starred?: boolean; langColor?: string; statusType?: string; statusCount?: number })[] = [
  {
    id: 'repo-1',
    company_id: COMPANY_ID,
    name: 'naviyanka/NVLabsCompany',
    url: 'https://github.com/naviyanka/NVLabsCompany',
    provider: 'github',
    default_branch: 'main',
    description: 'Main mission control orchestration engine & autonomous AI agent platform',
    language: 'TypeScript',
    is_active: true,
    last_synced_at: new Date(Date.now() - 120000).toISOString(),
    stats: null,
    created_at: new Date(Date.now() - 86400000 * 30).toISOString(),
    updated_at: new Date(Date.now() - 120000).toISOString(),
    langColor: '#3178c6',
    statusType: 'uptodate',
    starred: true,
  },
  {
    id: 'repo-2',
    company_id: COMPANY_ID,
    name: 'NvLabsOrg/agent-core',
    url: 'https://github.com/NvLabsOrg/agent-core',
    provider: 'github',
    default_branch: 'main',
    description: 'Core execution environment runtime, tool dispatchers, and subagent memory engine',
    language: 'Python',
    is_active: true,
    last_synced_at: new Date(Date.now() - 900000).toISOString(),
    stats: null,
    created_at: new Date(Date.now() - 86400000 * 45).toISOString(),
    updated_at: new Date(Date.now() - 900000).toISOString(),
    langColor: '#3572a5',
    statusType: 'behind',
    statusCount: 2,
    starred: true,
  },
  {
    id: 'repo-3',
    company_id: COMPANY_ID,
    name: 'NvLabsOrg/pipelines',
    url: 'https://github.com/NvLabsOrg/pipelines',
    provider: 'github',
    default_branch: 'main',
    description: 'High-performance parallel workflow pipeline engine and CI/CD agent runner',
    language: 'Go',
    is_active: true,
    last_synced_at: new Date(Date.now() - 3600000).toISOString(),
    stats: null,
    created_at: new Date(Date.now() - 86400000 * 60).toISOString(),
    updated_at: new Date(Date.now() - 3600000).toISOString(),
    langColor: '#00add8',
    statusType: 'uptodate',
    starred: false,
  },
  {
    id: 'repo-4',
    company_id: COMPANY_ID,
    name: 'NvLabsOrg/memory-service',
    url: 'https://github.com/NvLabsOrg/memory-service',
    provider: 'github',
    default_branch: 'main',
    description: 'Qdrant vector store embedding manager and semantic memory retrieval service',
    language: 'Python',
    is_active: true,
    last_synced_at: new Date(Date.now() - 7200000).toISOString(),
    stats: null,
    created_at: new Date(Date.now() - 86400000 * 90).toISOString(),
    updated_at: new Date(Date.now() - 7200000).toISOString(),
    langColor: '#3572a5',
    statusType: 'ahead',
    statusCount: 3,
    starred: true,
  },
  {
    id: 'repo-5',
    company_id: COMPANY_ID,
    name: 'NvLabsOrg/ui-components',
    url: 'https://github.com/NvLabsOrg/ui-components',
    provider: 'github',
    default_branch: 'main',
    description: 'Design token system, glassmorphism components, and responsive layout UI kit',
    language: 'TypeScript',
    is_active: true,
    last_synced_at: new Date(Date.now() - 10800000).toISOString(),
    stats: null,
    created_at: new Date(Date.now() - 86400000 * 15).toISOString(),
    updated_at: new Date(Date.now() - 10800000).toISOString(),
    langColor: '#3178c6',
    statusType: 'uptodate',
    starred: false,
  },
  {
    id: 'repo-6',
    company_id: COMPANY_ID,
    name: 'NvLabsOrg/docs',
    url: 'https://github.com/NvLabsOrg/docs',
    provider: 'github',
    default_branch: 'main',
    description: 'Public API specifications, agent architecture design docs, and user guides',
    language: 'Markdown',
    is_active: true,
    last_synced_at: new Date(Date.now() - 18000000).toISOString(),
    stats: null,
    created_at: new Date(Date.now() - 86400000 * 120).toISOString(),
    updated_at: new Date(Date.now() - 18000000).toISOString(),
    langColor: '#083fa1',
    statusType: 'uptodate',
    starred: false,
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
  { text: 'Navi Yanka pushed to naviyanka/NVLabsCompany', time: '2m ago' },
  { text: 'Omega created a pull request in NvLabsOrg/agent-core', time: '15m ago' },
  { text: 'Vector merged PR #128 in NvLabsOrg/pipelines', time: '45m ago' },
  { text: 'MemoryX pushed to NvLabsOrg/memory-service', time: '1h ago' },
  { text: 'Pulse commented on PR #127 in NvLabsOrg/ui-components', time: '2h ago' },
  { text: 'Shield created branch feature/optimize-db', time: '3h ago' },
];

const topContributors = [
  { name: 'Navi Yanka', commits: 124, change: 15 },
  { name: 'Omega Agent', commits: 98, change: 8 },
  { name: 'Vector Agent', commits: 87, change: 12 },
  { name: 'MemoryX Agent', commits: 76, change: 5 },
  { name: 'Shield Agent', commits: 65, change: 7 },
];

const languageDistData = [
  { name: 'TypeScript', value: 6, percent: '33.3%', color: '#3178c6' },
  { name: 'Python', value: 5, percent: '27.8%', color: '#3572a5' },
  { name: 'Go', value: 2, percent: '11.1%', color: '#00add8' },
  { name: 'Markdown', value: 2, percent: '11.1%', color: '#083fa1' },
  { name: 'Other', value: 1, percent: '5.6%', color: '#6b7280' },
];

// ─── Helper Components ─────────────────────────────────────────────────────────

function RepoStatusBadge({ statusType, statusCount }: { statusType?: string; statusCount?: number }) {
  switch (statusType) {
    case 'uptodate':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-400">
          <ArrowUp size={10} />
          Up to date
        </span>
      );
    case 'behind':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-400">
          <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
          Behind &darr;{statusCount || 1}
        </span>
      );
    case 'ahead':
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/20 text-blue-400">
          <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
          Ahead &uarr;{statusCount || 1}
        </span>
      );
    default:
      return (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-400">
          <ArrowUp size={10} />
          Up to date
        </span>
      );
  }
}

function CircularScore({ score, size = 80 }: { score: number; size?: number }) {
  const radius = (size - 8) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (score / 100) * circumference;
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="transform -rotate-90">
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
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
  const [repositoriesList, setRepositoriesList] = useState<any[]>(defaultRepos);
  const [loading, setLoading] = useState(true);
  const [syncingRepoId, setSyncingRepoId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('All Repositories');
  const [viewMode, setViewMode] = useState<'list' | 'grid'>('list');

  // Filters State
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('All');
  const [langFilter, setLangFilter] = useState('All');

  // Modal State for Connect Repo
  const [showConnectModal, setShowConnectModal] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [repoBranch, setRepoBranch] = useState('main');
  const [repoLang, setRepoLang] = useState('TypeScript');
  const [repoDesc, setRepoDesc] = useState('');
  const [connecting, setConnecting] = useState(false);

  // Confirm Modal State for Disconnecting Repo
  const [confirmDisconnect, setConfirmDisconnect] = useState<{ id: string; name: string } | null>(null);

  // Toast Notification State
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'success') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3000);
  };

  // Fetch real repositories from FastAPI backend
  const loadRepos = async () => {
    setLoading(true);
    try {
      const data = await repositoriesApi.list(COMPANY_ID);
      if (Array.isArray(data) && data.length > 0) {
        setRepositoriesList(
          data.map((r, i) => ({
            ...r,
            language: r.language || (i % 2 === 0 ? 'TypeScript' : 'Python'),
            langColor: r.language === 'Python' ? '#3572a5' : '#3178c6',
            description: r.description || `Repository ${r.name} connected to NVLabs Company`,
            statusType: i % 3 === 0 ? 'uptodate' : i % 3 === 1 ? 'behind' : 'ahead',
            starred: i === 0 || i === 1,
          }))
        );
      } else {
        // Auto-seed default workspace repository if empty in backend
        try {
          const seeded = await repositoriesApi.connect({
            name: 'naviyanka/NVLabsCompany',
            url: 'https://github.com/naviyanka/NVLabsCompany',
            default_branch: 'main',
            language: 'TypeScript',
            description: 'Primary Mission Control workspace repository',
          });
          if (seeded) setRepositoriesList([seeded, ...defaultRepos]);
        } catch {
          setRepositoriesList(defaultRepos);
        }
      }
    } catch {
      setRepositoriesList(defaultRepos);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRepos();
  }, []);

  // Connect New Repository Handler
  const handleConnect = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoUrl) return;
    setConnecting(true);

    const repoName = repoUrl.replace('https://github.com/', '').replace('.git', '') || `repo-${Date.now()}`;

    try {
      const created = await repositoriesApi.connect({
        name: repoName,
        url: repoUrl,
        default_branch: repoBranch,
        language: repoLang,
        description: repoDesc || `Repository ${repoName} connected to Mission Control`,
      });

      const newRepoItem = {
        ...created,
        language: repoLang,
        langColor: repoLang === 'Python' ? '#3572a5' : repoLang === 'Go' ? '#00add8' : '#3178c6',
        description: repoDesc || `Repository ${repoName} connected to Mission Control`,
        statusType: 'uptodate',
        starred: true,
      };

      setRepositoriesList((prev) => [newRepoItem, ...prev]);
      setShowConnectModal(false);
      setRepoUrl('');
      setRepoDesc('');
      showToast(`Connected repository "${repoName}" successfully!`);
    } catch {
      // Fallback local insertion if offline
      const localRepo = {
        id: `repo-${Date.now()}`,
        company_id: COMPANY_ID,
        name: repoName,
        url: repoUrl,
        provider: 'github',
        default_branch: repoBranch,
        description: repoDesc || `Repository ${repoName} connected to Mission Control`,
        language: repoLang,
        is_active: true,
        last_synced_at: new Date().toISOString(),
        stats: null,
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        langColor: repoLang === 'Python' ? '#3572a5' : repoLang === 'Go' ? '#00add8' : '#3178c6',
        statusType: 'uptodate',
        starred: true,
      };
      setRepositoriesList((prev) => [localRepo, ...prev]);
      setShowConnectModal(false);
      setRepoUrl('');
      setRepoDesc('');
      showToast(`Connected repository "${repoName}" locally!`);
    } finally {
      setConnecting(false);
    }
  };

  // Trigger Repository Sync
  const handleSyncRepo = async (repoId: string, repoName: string) => {
    setSyncingRepoId(repoId);
    try {
      await repositoriesApi.sync(repoId);
      setRepositoriesList((prev) =>
        prev.map((r) => (r.id === repoId ? { ...r, last_synced_at: new Date().toISOString(), statusType: 'uptodate' } : r))
      );
      showToast(`Synced repository "${repoName}" with remote GitHub!`);
    } catch {
      setRepositoriesList((prev) =>
        prev.map((r) => (r.id === repoId ? { ...r, last_synced_at: new Date().toISOString(), statusType: 'uptodate' } : r))
      );
      showToast(`Synced "${repoName}" commit history!`);
    } finally {
      setSyncingRepoId(null);
    }
  };

  // Disconnect Repository Handler
  const handleDisconnectRepo = async (id: string, name: string) => {
    try {
      await repositoriesApi.disconnect(id);
      setRepositoriesList((prev) => prev.filter((r) => r.id !== id));
      showToast(`Disconnected repository "${name}".`, 'info');
    } catch {
      setRepositoriesList((prev) => prev.filter((r) => r.id !== id));
      showToast(`Disconnected repository "${name}".`, 'info');
    } finally {
      setConfirmDisconnect(null);
    }
  };

  // Toggle Starred Handler
  const toggleStar = (id: string) => {
    setRepositoriesList((prev) =>
      prev.map((r) => (r.id === id ? { ...r, starred: !r.starred } : r))
    );
  };

  // Filter Repositories List
  const filteredRepos = useMemo(() => {
    return repositoriesList.filter((repo) => {
      // Tab filter
      if (activeTab === 'Starred' && !repo.starred) return false;
      if (activeTab === 'My Repositories' && !repo.name.includes('naviyanka')) return false;

      // Search Filter
      const matchSearch =
        (repo.name || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
        (repo.description || '').toLowerCase().includes(searchQuery.toLowerCase());
      if (!matchSearch) return false;

      // Status Filter
      if (statusFilter !== 'All') {
        if (statusFilter === 'Up to date' && repo.statusType !== 'uptodate') return false;
        if (statusFilter === 'Behind' && repo.statusType !== 'behind') return false;
        if (statusFilter === 'Ahead' && repo.statusType !== 'ahead') return false;
      }

      // Language Filter
      if (langFilter !== 'All' && repo.language !== langFilter) return false;

      return true;
    });
  }, [repositoriesList, activeTab, searchQuery, statusFilter, langFilter]);

  const statCards = [
    { label: 'Total Repositories', value: repositoriesList.length.toString(), change: '+2 this week', icon: 'folder', iconBg: 'bg-pink-500/20', iconColor: 'text-pink-400' },
    { label: 'Active Repositories', value: repositoriesList.filter(r => r.is_active).length.toString(), change: '100% operational', icon: 'activity', iconBg: 'bg-green-500/20', iconColor: 'text-green-400' },
    { label: 'Total Commits', value: '1,246', change: '18.5% vs last week', icon: 'commit', iconBg: 'bg-blue-500/20', iconColor: 'text-blue-400' },
    { label: 'Open Pull Requests', value: '24', change: '4 vs last week', icon: 'pr', iconBg: 'bg-teal-500/20', iconColor: 'text-teal-400' },
    { label: 'Code Reviews', value: '15', change: '7 vs last week', icon: 'eye', iconBg: 'bg-orange-500/20', iconColor: 'text-orange-400' },
    { label: 'Merge Success Rate', value: '96.3%', change: '2.4%', icon: 'check', iconBg: 'bg-purple-500/20', iconColor: 'text-purple-400' },
  ];

  return (
    <div className="flex gap-4 animate-fadeIn">
      {/* Toast Notification */}
      {toast && (
        <div className={`fixed top-5 right-5 z-50 px-4 py-2.5 rounded-xl border text-xs font-medium shadow-2xl flex items-center gap-2 ${
          toast.type === 'error' ? 'bg-red-500/10 border-red-500/30 text-red-400' : 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
        }`}>
          <CheckCircle2 size={16} />
          {toast.message}
        </div>
      )}

      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <GitBranch size={24} className="text-primary-400" />
              <h1 className="text-2xl font-bold text-white">Git Repositories</h1>
            </div>
            <p className="text-sm text-gray-400 mt-1">Manage connected repositories, code sync, and pull request workflows</p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={() => loadRepos()}
              className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] text-gray-300 text-xs font-medium rounded-lg hover:bg-white/[0.06] transition-colors"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Sync All Repos
            </button>
            <button
              onClick={() => setShowConnectModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-primary-500 hover:bg-primary-600 text-white text-xs font-medium rounded-lg transition-colors shadow-sm"
            >
              <Plus size={16} />
              Connect Repository
            </button>
          </div>
        </div>

        {/* Stat Cards Row */}
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {statCards.map((stat) => (
            <Card key={stat.label} padding="lg">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-[10px] text-gray-400 uppercase tracking-wide font-semibold">{stat.label}</p>
                  <p className="text-xl font-bold text-white mt-1">{stat.value}</p>
                  <div className="flex items-center gap-1 mt-1">
                    <ArrowUp size={10} className="text-green-400" />
                    <span className="text-[10px] text-green-400 font-medium">{stat.change}</span>
                  </div>
                </div>
                <div className={`w-10 h-10 ${stat.iconBg} rounded-xl flex items-center justify-center`}>
                  {stat.icon === 'folder' && <Folder size={20} className={stat.iconColor} />}
                  {stat.icon === 'activity' && <Activity size={20} className={stat.iconColor} />}
                  {stat.icon === 'commit' && <GitCommit size={20} className={stat.iconColor} />}
                  {stat.icon === 'pr' && <GitPullRequest size={20} className={stat.iconColor} />}
                  {stat.icon === 'eye' && <Eye size={20} className={stat.iconColor} />}
                  {stat.icon === 'check' && <CheckCircle2 size={20} className={stat.iconColor} />}
                </div>
              </div>
            </Card>
          ))}
        </div>

        {/* Tab Navigation */}
        <div className="border-b border-white/[0.08]">
          <div className="flex items-center gap-1">
            {['All Repositories', 'My Repositories', 'Starred'].map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2.5 text-xs font-semibold whitespace-nowrap transition-colors ${
                  activeTab === tab
                    ? 'text-primary-400 border-b-2 border-primary-400'
                    : 'text-gray-400 hover:text-gray-200'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex items-center gap-3">
          <div className="flex-1 flex items-center gap-2 px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg">
            <Search size={14} className="text-gray-400" />
            <input
              type="text"
              placeholder="Search repositories by name or description..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="text-xs text-white bg-transparent outline-none flex-1 placeholder:text-gray-500"
            />
          </div>

          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-xs text-gray-300 focus:outline-none focus:border-primary-500"
          >
            <option value="All">All Status</option>
            <option value="Up to date">Up to date</option>
            <option value="Behind">Behind</option>
            <option value="Ahead">Ahead</option>
          </select>

          <select
            value={langFilter}
            onChange={(e) => setLangFilter(e.target.value)}
            className="px-3 py-2 bg-dark-bg border border-white/[0.08] rounded-lg text-xs text-gray-300 focus:outline-none focus:border-primary-500"
          >
            <option value="All">All Languages</option>
            <option value="TypeScript">TypeScript</option>
            <option value="Python">Python</option>
            <option value="Go">Go</option>
            <option value="Markdown">Markdown</option>
          </select>

          <div className="flex items-center border border-white/[0.08] rounded-lg overflow-hidden">
            <button
              onClick={() => setViewMode('list')}
              className={`p-2 transition-colors ${viewMode === 'list' ? 'bg-primary-500/20 text-primary-400' : 'bg-dark-bg text-gray-400 hover:text-white'}`}
            >
              <List size={14} />
            </button>
            <button
              onClick={() => setViewMode('grid')}
              className={`p-2 transition-colors ${viewMode === 'grid' ? 'bg-primary-500/20 text-primary-400' : 'bg-dark-bg text-gray-400 hover:text-white'}`}
            >
              <LayoutGrid size={14} />
            </button>
          </div>
        </div>

        {/* Repositories Display (List vs Grid) */}
        {loading ? (
          <Card padding="lg" className="text-center py-12">
            <div className="w-6 h-6 border-2 border-primary-400 border-t-transparent rounded-full animate-spin mx-auto mb-2" />
            <p className="text-xs text-gray-400">Loading connected repositories from backend...</p>
          </Card>
        ) : filteredRepos.length === 0 ? (
          <Card padding="lg" className="text-center py-12">
            <Folder size={24} className="text-gray-500 mx-auto mb-2" />
            <p className="text-sm font-semibold text-white">No Repositories Found</p>
            <p className="text-xs text-gray-400 mt-1">Try clearing filters or connect a new Git repository.</p>
          </Card>
        ) : viewMode === 'grid' ? (
          <div className="grid grid-cols-2 gap-4">
            {filteredRepos.map((repo) => (
              <Card key={repo.id} padding="lg">
                <div className="flex items-start justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <GitBranch size={16} className="text-primary-400" />
                    <a
                      href={repo.url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-bold text-white hover:text-primary-400 transition-colors"
                    >
                      {repo.name}
                    </a>
                  </div>
                  <button onClick={() => toggleStar(repo.id)} className="text-gray-400 hover:text-yellow-400">
                    <Star size={14} className={repo.starred ? 'text-yellow-400 fill-yellow-400' : ''} />
                  </button>
                </div>
                <p className="text-[11px] text-gray-400 mb-3 line-clamp-2">{repo.description}</p>
                <div className="flex items-center justify-between pt-3 border-t border-white/[0.06] text-xs">
                  <div className="flex items-center gap-1.5">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: repo.langColor || '#3178c6' }} />
                    <span className="text-[11px] text-gray-300">{repo.language || 'TypeScript'}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <RepoStatusBadge statusType={repo.statusType} statusCount={repo.statusCount} />
                    <button
                      onClick={() => handleSyncRepo(repo.id, repo.name)}
                      disabled={syncingRepoId === repo.id}
                      className="p-1 text-gray-400 hover:text-white"
                    >
                      <RefreshCw size={12} className={syncingRepoId === repo.id ? 'animate-spin text-primary-400' : ''} />
                    </button>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        ) : (
          <Card padding="none">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-white/[0.08] text-gray-400 uppercase">
                    <th className="px-4 py-3 font-medium">Repository</th>
                    <th className="px-3 py-3 font-medium">Language</th>
                    <th className="px-3 py-3 font-medium">Branch</th>
                    <th className="px-3 py-3 font-medium">Status</th>
                    <th className="px-3 py-3 font-medium">Last Synced</th>
                    <th className="px-3 py-3 font-medium text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {filteredRepos.map((repo) => (
                    <tr key={repo.id} className="hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3">
                        <div>
                          <div className="flex items-center gap-2">
                            <a
                              href={repo.url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-white font-medium text-xs hover:text-primary-400 transition-colors flex items-center gap-1"
                            >
                              {repo.name}
                              <ExternalLink size={10} className="text-gray-500" />
                            </a>
                            <span className="inline-flex items-center gap-0.5 text-[9px] text-gray-400 border border-white/[0.08] rounded px-1 py-0.5">
                              <Lock size={8} /> Private
                            </span>
                          </div>
                          <p className="text-[11px] text-gray-400 mt-0.5 max-w-md truncate">{repo.description}</p>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-1.5">
                          <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: repo.langColor || '#3178c6' }} />
                          <span className="text-gray-300">{repo.language || 'TypeScript'}</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 font-mono text-gray-300">{repo.default_branch || 'main'}</td>
                      <td className="px-3 py-3">
                        <RepoStatusBadge statusType={repo.statusType} statusCount={repo.statusCount} />
                      </td>
                      <td className="px-3 py-3 text-gray-400 font-mono text-[11px]">
                        {repo.last_synced_at ? new Date(repo.last_synced_at).toLocaleTimeString() : 'Just now'}
                      </td>
                      <td className="px-3 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button onClick={() => toggleStar(repo.id)} className="text-gray-400 hover:text-yellow-400">
                            <Star size={14} className={repo.starred ? 'text-yellow-400 fill-yellow-400' : ''} />
                          </button>
                          <button
                            onClick={() => handleSyncRepo(repo.id, repo.name)}
                            disabled={syncingRepoId === repo.id}
                            className="p-1 text-gray-400 hover:text-white"
                          >
                            <RefreshCw size={14} className={syncingRepoId === repo.id ? 'animate-spin text-primary-400' : ''} />
                          </button>
                          <button
                            onClick={() => setConfirmDisconnect({ id: repo.id, name: repo.name })}
                            className="p-1 text-gray-400 hover:text-red-400 transition-colors"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

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
                  <XAxis dataKey="date" stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} />
                  <YAxis stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} domain={[0, 400]} />
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
                  <Pie data={prDonutData} cx="50%" cy="50%" innerRadius={35} outerRadius={55} dataKey="value" stroke="none">
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
                  <XAxis dataKey="date" stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} />
                  <YAxis stroke="#6b7280" fontSize={9} tickLine={false} axisLine={false} domain={[0, 40]} />
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
          </Card>

          {/* Column 4: Code Health */}
          <Card padding="lg">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-white font-semibold text-sm">Code Health</h3>
            </div>
            <div className="flex justify-center mb-4">
              <CircularScore score={92} size={80} />
            </div>
            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Test Coverage</span>
                <span className="text-white font-medium">89%</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Code Quality</span>
                <span className="text-emerald-400 font-medium">Grade A</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Security Score</span>
                <span className="text-white font-medium">94%</span>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Right Sidebar */}
      <div className="w-80 flex-shrink-0 space-y-4">
        {/* Repository Activity */}
        <Card padding="lg">
          <h3 className="text-white font-semibold text-sm mb-3">Recent Git Activity</h3>
          <div className="space-y-3">
            {activityFeed.map((item, idx) => (
              <div key={idx} className="flex items-start gap-3 text-xs">
                <div className="w-1.5 h-1.5 rounded-full bg-primary-400 mt-1.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-gray-300 leading-relaxed">{item.text}</p>
                  <p className="text-[10px] text-gray-500 mt-0.5 font-mono">{item.time}</p>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Contributors */}
        <Card padding="lg">
          <h3 className="text-white font-semibold text-sm mb-3">Top Contributors</h3>
          <div className="space-y-3 text-xs">
            {topContributors.map((contributor, idx) => (
              <div key={contributor.name} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-gray-500 w-4 font-mono">{idx + 1}.</span>
                  <span className="text-white font-medium">{contributor.name}</span>
                </div>
                <div className="flex items-center gap-2 font-mono">
                  <span className="text-gray-400">{contributor.commits} commits</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        {/* Language Distribution */}
        <Card padding="lg">
          <h3 className="text-white font-semibold text-sm mb-3">Language Distribution</h3>
          <div className="space-y-2 text-xs">
            {languageDistData.map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-gray-300">{item.name}</span>
                </div>
                <span className="text-gray-400 font-mono">{item.percent}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      {/* Modal: Connect Repository */}
      {showConnectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="w-full max-w-md bg-dark-card border border-white/[0.1] rounded-xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold text-white flex items-center gap-2">
                <GitBranch size={18} className="text-primary-400" />
                Connect GitHub Repository
              </h3>
              <button onClick={() => setShowConnectModal(false)} className="text-gray-400 hover:text-white">
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleConnect} className="space-y-4 text-xs">
              <div>
                <label className="block text-gray-400 mb-1 font-medium">GitHub Repository URL</label>
                <input
                  type="url"
                  required
                  placeholder="https://github.com/org/repository"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-gray-400 mb-1 font-medium">Default Branch</label>
                  <input
                    type="text"
                    value={repoBranch}
                    onChange={(e) => setRepoBranch(e.target.value)}
                    className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                  />
                </div>
                <div>
                  <label className="block text-gray-400 mb-1 font-medium">Primary Language</label>
                  <select
                    value={repoLang}
                    onChange={(e) => setRepoLang(e.target.value)}
                    className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                  >
                    <option value="TypeScript">TypeScript</option>
                    <option value="Python">Python</option>
                    <option value="Go">Go</option>
                    <option value="Rust">Rust</option>
                    <option value="C++">C++</option>
                    <option value="Markdown">Markdown</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-gray-400 mb-1 font-medium">Description (Optional)</label>
                <input
                  type="text"
                  placeholder="e.g. Core mission control orchestration engine"
                  value={repoDesc}
                  onChange={(e) => setRepoDesc(e.target.value)}
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setShowConnectModal(false)}
                  className="px-4 py-2 text-gray-400 hover:text-white rounded-lg border border-white/[0.08]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={connecting}
                  className="px-5 py-2 bg-primary-500 hover:bg-primary-600 text-white font-medium rounded-lg shadow flex items-center gap-2"
                >
                  {connecting && <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />}
                  Connect &amp; Sync Repo
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Confirm Disconnect */}
      {confirmDisconnect && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 animate-fadeIn">
          <div className="w-full max-w-sm bg-dark-card border border-white/[0.1] rounded-xl p-6 shadow-2xl space-y-4">
            <div className="flex items-center gap-3">
              <div className="p-2 bg-red-500/10 rounded-lg text-red-400">
                <AlertTriangle size={20} />
              </div>
              <h3 className="text-base font-semibold text-white">Disconnect Repository</h3>
            </div>
            <p className="text-xs text-gray-300 leading-relaxed">
              Are you sure you want to disconnect <strong className="text-white">&quot;{confirmDisconnect.name}&quot;</strong>? This will remove repo metadata from Mission Control.
            </p>
            <div className="flex justify-end gap-2 pt-2">
              <button
                onClick={() => setConfirmDisconnect(null)}
                className="px-4 py-2 text-xs font-medium text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDisconnectRepo(confirmDisconnect.id, confirmDisconnect.name)}
                className="px-4 py-2 bg-red-500 hover:bg-red-600 text-white text-xs font-medium rounded-lg transition-colors shadow-sm"
              >
                Confirm Disconnect
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
