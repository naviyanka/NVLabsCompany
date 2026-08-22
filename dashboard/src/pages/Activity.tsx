import { useState, useEffect, useMemo } from 'react';
import { Card } from '@/components/common/Card';
import { Spinner } from '@/components/common/Spinner';
import { useEventStream } from '@/hooks/useEventStream';
import { activityApi, type ActivityRowItem, type ActivityFeedData } from '@/api/activity';
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
  RefreshCw,
  Wifi,
  WifiOff,
} from 'lucide-react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';

const pageTabs = ['All Activity', 'System Events', 'Agent Activity', 'Task Activity', 'Pipeline Activity'];

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

export function Activity() {
  const [data, setData] = useState<ActivityFeedData | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('All Activity');

  // Filters
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedType, setSelectedType] = useState('All Types');
  const [selectedStatus, setSelectedStatus] = useState('All Status');

  // Pagination
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // Real-time SSE Stream hook
  const { events: liveEvents, isConnected } = useEventStream({
    maxEvents: 50,
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const res = await activityApi.fetchActivityData();
      setData(res);
    } catch (err) {
      console.error('Failed to load activity data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Merge live SSE events into display items
  const allRows = useMemo(() => {
    if (!data) return [];
    const sseRows: ActivityRowItem[] = liveEvents.map((evt) => ({
      id: `sse-${evt.event_id}`,
      event: `Event: ${evt.event_type}`,
      typeBadge: 'LIVE STREAM',
      typeBadgeColor: 'bg-emerald-500/20 text-emerald-400',
      description: JSON.stringify(evt.data || {}),
      metadata: `Channel: ${evt.channel || 'global'}`,
      agent: String(evt.data?.agent_id || 'System Stream'),
      time: new Date(evt.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      timestamp: evt.timestamp,
      status: 'DELIVERED',
      statusColor: 'bg-emerald-500/20 text-emerald-400',
      rawType: 'stream',
    }));

    return [...sseRows, ...data.rows];
  }, [data, liveEvents]);

  // Filtered rows
  const filteredRows = useMemo(() => {
    return allRows.filter((row) => {
      // Tab filter
      if (activeTab === 'System Events' && row.typeBadge !== 'SYSTEM') return false;
      if (activeTab === 'Agent Activity' && row.typeBadge !== 'AGENT' && !row.agent.includes('Agent')) return false;
      if (activeTab === 'Task Activity' && row.typeBadge !== 'TASK') return false;

      // Dropdown type filter
      if (selectedType !== 'All Types' && row.typeBadge !== selectedType) return false;

      // Dropdown status filter
      if (selectedStatus !== 'All Status' && row.status.toLowerCase() !== selectedStatus.toLowerCase()) return false;

      // Search query
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchEvent = row.event.toLowerCase().includes(q);
        const matchDesc = row.description.toLowerCase().includes(q);
        const matchAgent = row.agent.toLowerCase().includes(q);
        if (!matchEvent && !matchDesc && !matchAgent) return false;
      }

      return true;
    });
  }, [allRows, activeTab, selectedType, selectedStatus, searchQuery]);

  // Paginated rows
  const paginatedRows = useMemo(() => {
    const start = (currentPage - 1) * pageSize;
    return filteredRows.slice(start, start + pageSize);
  }, [filteredRows, currentPage, pageSize]);

  const totalPages = Math.ceil(filteredRows.length / pageSize) || 1;

  const statCardsData = [
    {
      label: 'Total Activities',
      value: (data?.stats.totalActivities ?? 0).toLocaleString(),
      change: '18.6%',
      changeUp: true,
      changeSuffix: 'vs last 7d',
      icon: 'chart',
      iconBg: 'bg-pink-500/20',
      iconColor: 'text-pink-400',
    },
    {
      label: 'Successful Actions',
      value: (data?.stats.completedTasks ?? 0).toLocaleString(),
      change: '16.3%',
      changeUp: true,
      changeSuffix: 'vs last 7d',
      icon: 'check',
      iconBg: 'bg-green-500/20',
      iconColor: 'text-green-400',
    },
    {
      label: 'Failed Actions',
      value: (data?.stats.failedTasks ?? 0).toLocaleString(),
      change: '9.4%',
      changeUp: false,
      changeSuffix: 'vs last 7d',
      icon: 'x',
      iconBg: 'bg-red-500/20',
      iconColor: 'text-red-400',
    },
    {
      label: 'Avg Response',
      value: `${data?.stats.avgResponseTimeMs ?? 142}ms`,
      change: '5.7%',
      changeUp: true,
      changeSuffix: 'vs last 7d',
      icon: 'clock',
      iconBg: 'bg-blue-500/20',
      iconColor: 'text-blue-400',
    },
    {
      label: 'Active Agents',
      value: String(data?.stats.activeAgentsCount ?? 0),
      change: '',
      changeUp: true,
      changeSuffix: '',
      icon: 'users',
      iconBg: 'bg-teal-500/20',
      iconColor: 'text-teal-400',
    },
    {
      label: 'Active Incidents',
      value: String(data?.stats.activeIncidentsCount ?? 0),
      change: '',
      changeUp: false,
      changeSuffix: '',
      icon: 'zap',
      iconBg: 'bg-purple-500/20',
      iconColor: 'text-purple-400',
    },
  ];

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Spinner size="lg" />
      </div>
    );
  }

  return (
    <div className="flex gap-4">
      {/* Main Content Area */}
      <div className="flex-1 min-w-0 space-y-6">
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <div className="flex items-center gap-3">
              <ActivityIcon size={24} className="text-indigo-400" />
              <h1 className="text-2xl font-bold text-white">Activity</h1>
              <span
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${
                  isConnected
                    ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                    : 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                }`}
              >
                {isConnected ? <Wifi size={12} /> : <WifiOff size={12} />}
                {isConnected ? 'SSE Stream Live' : 'Polling Backend'}
              </span>
            </div>
            <p className="text-sm text-gray-400 mt-1">
              Real-time overview of system activity, agent runs, and incidents across the platform
            </p>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={loadData}
              className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors"
            >
              <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
            <button className="flex items-center gap-2 px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 hover:text-white transition-colors">
              <Calendar size={14} />
              Last 7 Days
              <ChevronDown size={14} />
            </button>
          </div>
        </div>

        {/* Stat Cards Row */}
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {statCardsData.map((stat) => (
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
                        <ArrowDown size={10} className="text-red-400" />
                      )}
                      <span className={`text-[10px] ${stat.changeUp ? 'text-green-400' : 'text-red-400'}`}>
                        {stat.change}
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
                onClick={() => {
                  setActiveTab(tab);
                  setCurrentPage(1);
                }}
                className={`px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors ${
                  tab === activeTab
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
            <input
              type="text"
              placeholder="Search activity..."
              value={searchQuery}
              onChange={(e) => {
                setSearchQuery(e.target.value);
                setCurrentPage(1);
              }}
              className="bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none w-full"
            />
          </div>
          <select
            value={selectedType}
            onChange={(e) => {
              setSelectedType(e.target.value);
              setCurrentPage(1);
            }}
            className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8 cursor-pointer"
          >
            <option>All Types</option>
            <option>TASK</option>
            <option>INCIDENT</option>
            <option>SYSTEM</option>
            <option>LIVE STREAM</option>
          </select>
          <select
            value={selectedStatus}
            onChange={(e) => {
              setSelectedStatus(e.target.value);
              setCurrentPage(1);
            }}
            className="px-3 py-2 bg-dark-surface border border-white/[0.08] rounded-lg text-sm text-gray-400 appearance-none pr-8 cursor-pointer"
          >
            <option>All Status</option>
            <option>COMPLETED</option>
            <option>FAILED</option>
            <option>PENDING</option>
            <option>HEALTHY</option>
          </select>
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
                {paginatedRows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-500">
                      No activity found matching the criteria.
                    </td>
                  </tr>
                ) : (
                  paginatedRows.map((row) => (
                    <tr key={row.id} className="border-b border-white/[0.05] hover:bg-white/[0.02] transition-colors">
                      <td className="px-4 py-3">
                        <p className="text-xs text-white font-medium">{row.event}</p>
                        <span className={`text-[10px] px-2 py-0.5 rounded mt-1 inline-block ${row.typeBadgeColor}`}>
                          {row.typeBadge}
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <p className="text-xs text-gray-300 line-clamp-1">{row.description}</p>
                        <p className="text-[10px] text-gray-500 mt-0.5">{row.metadata}</p>
                      </td>
                      <td className="px-3 py-3">
                        <span className="text-xs text-gray-300 font-mono">{row.agent}</span>
                      </td>
                      <td className="px-3 py-3">
                        <span className="text-[10px] text-gray-500 whitespace-nowrap">{row.time}</span>
                      </td>
                      <td className="px-3 py-3">
                        <span className={`text-[10px] px-2 py-1 rounded font-medium ${row.statusColor}`}>
                          {row.status}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-right">
                        <button className="text-gray-500 hover:text-gray-300">
                          <MoreHorizontal size={14} />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          <div className="px-4 py-3 flex items-center justify-between border-t border-white/[0.05]">
            <span className="text-[10px] text-gray-500">
              Showing {filteredRows.length > 0 ? (currentPage - 1) * pageSize + 1 : 0} to{' '}
              {Math.min(currentPage * pageSize, filteredRows.length)} of {filteredRows.length} activities
            </span>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={currentPage === 1}
                className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] disabled:opacity-40"
              >
                <ChevronLeft size={12} />
              </button>

              {Array.from({ length: totalPages }, (_, i) => i + 1).slice(0, 5).map((pg) => (
                <button
                  key={pg}
                  onClick={() => setCurrentPage(pg)}
                  className={`w-7 h-7 flex items-center justify-center rounded text-[10px] ${
                    pg === currentPage ? 'bg-indigo-500/20 text-indigo-400 font-bold' : 'text-gray-500 hover:bg-white/[0.05]'
                  }`}
                >
                  {pg}
                </button>
              ))}

              <button
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={currentPage === totalPages}
                className="w-7 h-7 flex items-center justify-center rounded text-gray-500 hover:bg-white/[0.05] disabled:opacity-40"
              >
                <ChevronRight size={12} />
              </button>
            </div>
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setCurrentPage(1);
              }}
              className="px-2 py-1 bg-dark-bg border border-white/[0.05] rounded text-[10px] text-gray-400 appearance-none cursor-pointer"
            >
              <option value={10}>10 / page</option>
              <option value={20}>20 / page</option>
              <option value={50}>50 / page</option>
            </select>
          </div>
        </Card>
      </div>

      {/* Right Sidebar */}
      <div className="w-80 flex-shrink-0 space-y-4">
        {/* Live Activity Feed Widget */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h3 className="text-white font-semibold text-sm">Live SSE Feed</h3>
              <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Live
              </span>
            </div>
            <span className="text-[10px] text-indigo-400 cursor-pointer">{liveEvents.length} Events</span>
          </div>
          <div className="space-y-3 max-h-60 overflow-y-auto pr-1">
            {liveEvents.length === 0 ? (
              <p className="text-xs text-gray-500 py-2">Listening for real-time events on SSE channel...</p>
            ) : (
              liveEvents.slice(0, 5).map((item) => (
                <div key={item.event_id} className="border-b border-white/[0.05] pb-3 last:border-0 last:pb-0">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-gray-500">
                      {new Date(item.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                    </span>
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono">
                      {item.event_type}
                    </span>
                  </div>
                  <p className="text-xs text-gray-300 mt-1 line-clamp-2">
                    {JSON.stringify(item.data)}
                  </p>
                </div>
              ))
            )}
          </div>
        </Card>

        {/* Activity by Type (Pie Chart) */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Activity Distribution</h3>
          </div>
          <div className="h-44 relative">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data?.typeDistribution || []}
                  cx="50%"
                  cy="50%"
                  innerRadius={45}
                  outerRadius={65}
                  dataKey="value"
                  stroke="none"
                >
                  {(data?.typeDistribution || []).map((entry) => (
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
                <p className="text-lg font-bold text-white">{filteredRows.length}</p>
                <p className="text-[9px] text-gray-500">Items</p>
              </div>
            </div>
          </div>
          <div className="space-y-1.5 mt-3">
            {(data?.typeDistribution || []).map((item) => (
              <div key={item.name} className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-[10px] text-gray-400">{item.name}</span>
                </div>
                <span className="text-[10px] text-gray-500">
                  {item.percentage} ({item.value})
                </span>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Active Agents */}
        <Card padding="lg">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-white font-semibold text-sm">Top Active Agents</h3>
          </div>
          <div className="space-y-3">
            {(data?.topAgents || []).map((agent, idx) => {
              const maxCount = data?.topAgents[0]?.count ?? 1;
              const barWidth = (agent.count / maxCount) * 100;
              return (
                <div key={agent.name}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-gray-500 w-4">{idx + 1}.</span>
                      <span className="text-xs text-white font-medium">{agent.name}</span>
                    </div>
                    <span className="text-[10px] text-gray-400">{agent.count} runs</span>
                  </div>
                  <div className="h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{ width: `${barWidth}%`, backgroundColor: agent.color }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      </div>
    </div>
  );
}
