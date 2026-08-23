import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Activity as ActivityIcon,
  Search,
  CheckCircle2,
  Zap,
  Radio,
  Pause,
  Play,
  Download,
  AlertTriangle,
  Terminal,
  LayoutList,
  BarChart3,
  RefreshCw,
  Cpu,
  GitCommit,
  Shield,
  Database,
  Copy,
  Check,
  Filter,
  Clock,
  ChevronRight,
  Layers,
} from 'lucide-react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { StatCard } from '@/components/common/StatCard';
import { Drawer } from '@/components/common/Drawer';
import { apiClient } from '@/api/client';

export type ActivitySeverity = 'info' | 'warning' | 'error' | 'critical';
export type ActivityStatus = 'success' | 'failed' | 'in_progress';
export type ActivityCategory = 'Task' | 'Pipeline' | 'Agent' | 'System' | 'Git' | 'Policy' | 'Memory';

export interface ActivityLog {
  id: string;
  event: string;
  type: ActivityCategory;
  description: string;
  agent: string;
  time: string;
  timestamp: number;
  status: ActivityStatus;
  severity: ActivitySeverity;
  latency_ms: number;
  metadata?: string;
  raw_payload?: Record<string, unknown>;
}

const SEVERITY_COLORS: Record<ActivitySeverity, { bg: string; text: string; border: string; dot: string }> = {
  info: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/20', dot: 'bg-blue-400' },
  warning: { bg: 'bg-amber-500/10', text: 'text-amber-400', border: 'border-amber-500/20', dot: 'bg-amber-400' },
  error: { bg: 'bg-rose-500/10', text: 'text-rose-400', border: 'border-rose-500/20', dot: 'bg-rose-500' },
  critical: { bg: 'bg-red-600/20', text: 'text-red-300', border: 'border-red-500/40', dot: 'bg-red-500 animate-ping' },
};

const INITIAL_LOGS: ActivityLog[] = [
  {
    id: 'evt-9041',
    event: 'A* Pathfinding Strategy Recalculated',
    type: 'Agent',
    description: 'Dwight-QA dynamically adjusted collision avoidance vector around Executive Suite lounge',
    agent: 'Dwight (QA Lead)',
    time: 'Just now',
    timestamp: Date.now(),
    status: 'success',
    severity: 'info',
    latency_ms: 48,
    raw_payload: { grid_x: 24, grid_y: 18, obstacle_count: 3, algorithm: 'AStarHeuristicManhattan' },
  },
  {
    id: 'evt-9040',
    event: 'Policy Enforcement Audit Evaluated',
    type: 'Policy',
    description: 'Evaluated budget threshold policy for multi-agent swarm token allocation',
    agent: 'Toby (Compliance Officer)',
    time: '1m ago',
    timestamp: Date.now() - 60000,
    status: 'success',
    severity: 'info',
    latency_ms: 112,
    raw_payload: { policy_id: 'pol_budget_max_800', result: 'APPROVED', token_usage: 41200 },
  },
  {
    id: 'evt-9039',
    event: 'Git Pull Request Verification Triggered',
    type: 'Git',
    description: 'Jim-PR-Reviewer initiated automated static graph impact analysis on branch main',
    agent: 'Jim (PR Reviewer)',
    time: '2m ago',
    timestamp: Date.now() - 120000,
    status: 'in_progress',
    severity: 'warning',
    latency_ms: 320,
    raw_payload: { pr_id: 'PR-148', commit_hash: '831971c', blast_radius: '14 files affected' },
  },
  {
    id: 'evt-9038',
    event: 'Graph Contradiction Engine Warning',
    type: 'Memory',
    description: 'Detected conflicting memory assertion between Angela-Budget and Kevin-Data regarding Q3 spend forecast',
    agent: 'Angela (Budget Auditor)',
    time: '3m ago',
    timestamp: Date.now() - 180000,
    status: 'failed',
    severity: 'error',
    latency_ms: 240,
    raw_payload: { node_a: 'mem_spend_q3_420k', node_b: 'mem_spend_q3_390k', contradiction_score: 0.88 },
  },
  {
    id: 'evt-9037',
    event: 'Continuous Integration Pipeline Complete',
    type: 'Pipeline',
    description: 'CI Build #4829 completed TypeScript static verification with zero errors',
    agent: 'Ryan (DevOps Lead)',
    time: '5m ago',
    timestamp: Date.now() - 300000,
    status: 'success',
    severity: 'info',
    latency_ms: 1850,
    raw_payload: { pipeline_id: 'pipe_ci_main_4829', exit_code: 0, test_suite_passed: 42 },
  },
  {
    id: 'evt-9036',
    event: 'High Token Concurrency Spike',
    type: 'System',
    description: 'Ingestion rate spiked above 45 events/min during multi-agent standup sync',
    agent: 'Pam (Docs & Comms)',
    time: '7m ago',
    timestamp: Date.now() - 420000,
    status: 'success',
    severity: 'warning',
    latency_ms: 95,
    raw_payload: { active_threads: 12, queue_depth: 4, memory_footprint_mb: 384 },
  },
  {
    id: 'evt-9035',
    event: 'Agent Tool Dispatch Execution',
    type: 'Task',
    description: 'Creed-Security initiated sandbox security audit scan on dependency tree',
    agent: 'Creed (Security Specialist)',
    time: '10m ago',
    timestamp: Date.now() - 600000,
    status: 'success',
    severity: 'info',
    latency_ms: 640,
    raw_payload: { scan_target: 'node_modules', vulnerabilities_found: 0, risk_score: 'LOW' },
  },
  {
    id: 'evt-9034',
    event: 'Critical API Throttling Event',
    type: 'System',
    description: 'Rate limit warning threshold reached for external LLM inference gateway',
    agent: 'Oscar (Financial Analyst)',
    time: '12m ago',
    timestamp: Date.now() - 720000,
    status: 'failed',
    severity: 'critical',
    latency_ms: 1420,
    raw_payload: { gateway_endpoint: 'https://api.openai.com/v1/chat/completions', retry_after_s: 5 },
  },
];

const MOCK_SAMPLE_EVENTS: Partial<ActivityLog>[] = [
  { event: 'A* Navigation Step', type: 'Agent', description: 'Agent calculated path to lounge water cooler', severity: 'info', agent: 'Dwight (QA Lead)' },
  { event: 'Git Webhook Event Recv', type: 'Git', description: 'Received push payload on branch feature/office-2d', severity: 'info', agent: 'Jim (PR Reviewer)' },
  { event: 'Memory Graph Node Added', type: 'Memory', description: 'Ingested entity node #mem_8492 for project roadmap', severity: 'info', agent: 'Pam (Docs & Comms)' },
  { event: 'Pipeline Step Succeeded', type: 'Pipeline', description: 'Vite production build bundled dist artifacts in 840ms', severity: 'info', agent: 'Ryan (DevOps Lead)' },
  { event: 'Policy Budget Threshold Checked', type: 'Policy', description: 'Monthly budget consumption reached 64.2%', severity: 'warning', agent: 'Angela (Budget Auditor)' },
  { event: 'Agent Execution Error', type: 'Task', description: 'Timeout waiting for CLI backend response', severity: 'error', agent: 'Creed (Security Specialist)' },
];

export function Activity() {
  const [logs, setLogs] = useState<ActivityLog[]>(INITIAL_LOGS);
  const [search, setSearch] = useState('');
  const [selectedType, setSelectedType] = useState<string>('all');
  const [selectedSeverity, setSelectedSeverity] = useState<string>('all');
  const [selectedStatus, setSelectedStatus] = useState<string>('all');
  const [selectedLog, setSelectedLog] = useState<ActivityLog | null>(null);
  const [isLive, setIsLive] = useState<boolean>(true);
  const [viewMode, setViewMode] = useState<'list' | 'terminal' | 'analytics'>('list');
  const [copiedId, setCopiedId] = useState<boolean>(false);

  // Fetch initial activity logs from API if available
  useEffect(() => {
    async function loadActivity() {
      try {
        const res = await apiClient.get<{ items: ActivityLog[] }>(
          '/api/v1/companies/00000000-0000-4000-8000-000000000001/activity'
        );
        if (res?.items && res.items.length > 0) {
          const formatted = res.items.map((item, i) => ({
            ...item,
            timestamp: item.timestamp || Date.now() - i * 60000,
            severity: item.severity || (item.status === 'failed' ? 'error' : 'info'),
            latency_ms: item.latency_ms || Math.floor(Math.random() * 300) + 40,
          }));
          setLogs(formatted);
        }
      } catch {
        // Keep initial mock logs if API returns error
      }
    }
    loadActivity();
  }, []);

  // Simulate real-time streaming incoming logs
  useEffect(() => {
    if (!isLive) return;

    const interval = setInterval(() => {
      const sample = MOCK_SAMPLE_EVENTS[Math.floor(Math.random() * MOCK_SAMPLE_EVENTS.length)];
      if (!sample) return;

      const newId = `evt-${Math.floor(Math.random() * 9000) + 1000}`;
      const newLog: ActivityLog = {
        id: newId,
        event: sample.event || 'Telemetry Event',
        type: (sample.type as ActivityCategory) || 'System',
        description: sample.description || 'Automated background execution trace',
        agent: sample.agent || 'System Service',
        time: 'Just now',
        timestamp: Date.now(),
        status: (sample.severity === 'error' || sample.severity === 'critical') ? 'failed' : 'success',
        severity: (sample.severity as ActivitySeverity) || 'info',
        latency_ms: Math.floor(Math.random() * 250) + 30,
        raw_payload: {
          event_id: newId,
          simulated: true,
          cpu_load: `${(Math.random() * 15 + 10).toFixed(1)}%`,
          thread_id: `worker-${Math.floor(Math.random() * 8) + 1}`,
        },
      };

      setLogs((prev) => [newLog, ...prev.slice(0, 49)]);
    }, 4000);

    return () => clearInterval(interval);
  }, [isLive]);

  // Filter logs based on search, category, severity, and status
  const filtered = useMemo(() => {
    return logs.filter((log) => {
      if (selectedType !== 'all' && log.type.toLowerCase() !== selectedType.toLowerCase()) return false;
      if (selectedSeverity !== 'all' && log.severity !== selectedSeverity) return false;
      if (selectedStatus !== 'all' && log.status !== selectedStatus) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          log.event.toLowerCase().includes(q) ||
          log.description.toLowerCase().includes(q) ||
          log.agent.toLowerCase().includes(q) ||
          log.id.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [logs, search, selectedType, selectedSeverity, selectedStatus]);

  // Metric Computations
  const totalEvents = logs.length;
  const successCount = logs.filter((l) => l.status === 'success').length;
  const successRate = totalEvents > 0 ? ((successCount / totalEvents) * 100).toFixed(1) : '100';
  const avgLatency = Math.round(
    logs.reduce((acc, curr) => acc + (curr.latency_ms || 100), 0) / (totalEvents || 1)
  );

  // Chart Data Preparation
  const chartData = useMemo(() => {
    const intervals: Record<string, { time: string; events: number; errors: number }> = {};
    const now = Date.now();
    for (let i = 9; i >= 0; i--) {
      const label = `${i * 2}m ago`;
      intervals[label] = { time: label, events: 0, errors: 0 };
    }

    logs.forEach((log) => {
      const diffMins = Math.floor((now - log.timestamp) / 60000);
      const bucketIdx = Math.min(Math.floor(diffMins / 2), 9);
      const label = `${bucketIdx * 2}m ago`;
      if (intervals[label]) {
        intervals[label].events += 1;
        if (log.status === 'failed' || log.severity === 'error' || log.severity === 'critical') {
          intervals[label].errors += 1;
        }
      }
    });

    return Object.values(intervals).reverse();
  }, [logs]);

  const severityPieData = useMemo(() => {
    const counts = { info: 0, warning: 0, error: 0, critical: 0 };
    logs.forEach((l) => {
      counts[l.severity] = (counts[l.severity] || 0) + 1;
    });
    return [
      { name: 'Info', value: counts.info, color: '#38BDF8' },
      { name: 'Warning', value: counts.warning, color: '#F59E0B' },
      { name: 'Error', value: counts.error, color: '#F43F5E' },
      { name: 'Critical', value: counts.critical, color: '#EF4444' },
    ];
  }, [logs]);

  const agentLeaderboard = useMemo(() => {
    const counts: Record<string, number> = {};
    logs.forEach((l) => {
      counts[l.agent] = (counts[l.agent] || 0) + 1;
    });
    return Object.entries(counts)
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 5);
  }, [logs]);

  // Export handlers
  const handleExportJson = useCallback(() => {
    const jsonStr = JSON.stringify(filtered, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_telemetry_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filtered]);

  const handleExportCsv = useCallback(() => {
    const headers = ['ID', 'Event', 'Type', 'Severity', 'Status', 'Agent', 'Latency(ms)', 'Time', 'Description'];
    const rows = filtered.map((l) => [
      l.id,
      `"${l.event.replace(/"/g, '""')}"`,
      l.type,
      l.severity,
      l.status,
      `"${l.agent.replace(/"/g, '""')}"`,
      l.latency_ms,
      l.time,
      `"${l.description.replace(/"/g, '""')}"`,
    ]);
    const csvStr = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvStr], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_telemetry_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filtered]);

  const getCategoryIcon = (type: ActivityCategory) => {
    switch (type) {
      case 'Agent': return <Cpu className="w-3.5 h-3.5 text-blue-400" />;
      case 'Git': return <GitCommit className="w-3.5 h-3.5 text-purple-400" />;
      case 'Policy': return <Shield className="w-3.5 h-3.5 text-emerald-400" />;
      case 'Memory': return <Database className="w-3.5 h-3.5 text-amber-400" />;
      case 'Pipeline': return <RefreshCw className="w-3.5 h-3.5 text-cyan-400" />;
      case 'Task': return <ActivityIcon className="w-3.5 h-3.5 text-indigo-400" />;
      default: return <Zap className="w-3.5 h-3.5 text-gray-400" />;
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Radio className={`w-5 h-5 ${isLive ? 'text-[#22C55E] animate-pulse' : 'text-gray-500'}`} />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight flex items-center gap-3">
              Real-Time Audit Log & Telemetry Traces
              <span className={`text-xs px-2 py-0.5 rounded-full font-mono border ${
                isLive ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-gray-500/10 text-gray-400 border-gray-500/20'
              }`}>
                {isLive ? 'LIVE STREAMING' : 'PAUSED'}
              </span>
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            System events, autonomous agent tool dispatches, A* pathfinding, and policy verification lifecycle
          </p>
        </div>

        {/* Top Controls */}
        <div className="flex items-center gap-2">
          {/* Live Stream Toggle */}
          <button
            onClick={() => setIsLive(!isLive)}
            className={`px-3 py-1.5 rounded-[6px] text-xs font-mono font-medium border flex items-center gap-2 transition-all cursor-pointer ${
              isLive
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20'
                : 'bg-white/[0.04] border-white/[0.1] text-gray-300 hover:bg-white/[0.08]'
            }`}
          >
            {isLive ? <Pause size={14} /> : <Play size={14} />}
            <span>{isLive ? 'Pause Stream' : 'Resume Live Stream'}</span>
          </button>

          {/* View Mode Switcher */}
          <div className="flex items-center bg-[#101012] border border-white/[0.08] rounded-[6px] p-0.5">
            <button
              onClick={() => setViewMode('list')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'list' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Detailed List View"
            >
              <LayoutList size={13} />
              <span className="hidden sm:inline">List</span>
            </button>
            <button
              onClick={() => setViewMode('terminal')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'terminal' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="CLI Terminal Log Stream"
            >
              <Terminal size={13} />
              <span className="hidden sm:inline">Terminal</span>
            </button>
            <button
              onClick={() => setViewMode('analytics')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'analytics' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Analytics Charts"
            >
              <BarChart3 size={13} />
              <span className="hidden sm:inline">Analytics</span>
            </button>
          </div>

          {/* Export Dropdown */}
          <div className="flex items-center gap-1">
            <button
              onClick={handleExportJson}
              className="px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.08] border border-white/[0.08] text-gray-300 hover:text-white rounded-[6px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer"
              title="Export as JSON"
            >
              <Download size={13} />
              <span className="hidden sm:inline">JSON</span>
            </button>
            <button
              onClick={handleExportCsv}
              className="px-2.5 py-1.5 bg-[#141416] hover:bg-white/[0.08] border border-white/[0.08] text-gray-300 hover:text-white rounded-[6px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer"
              title="Export as CSV"
            >
              <Download size={13} />
              <span className="hidden sm:inline">CSV</span>
            </button>
          </div>
        </div>
      </div>

      {/* Telemetry Metrics Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Activity Events"
          value={totalEvents}
          subValue="Telemetry Traces"
          change={isLive ? 'Streaming active' : 'Stream paused'}
          changeType={isLive ? 'positive' : 'neutral'}
          icon={<ActivityIcon className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="Execution Success Rate"
          value={`${successRate}%`}
          subValue={`${successCount} / ${totalEvents} passed`}
          change="Zero crash policy"
          changeType="positive"
          icon={<CheckCircle2 className="w-4 h-4 text-emerald-400" />}
        />
        <StatCard
          label="Avg Latency (ms)"
          value={`${avgLatency} ms`}
          subValue="Real-time Dispatch"
          change="Optimal response"
          changeType="positive"
          icon={<Clock className="w-4 h-4 text-cyan-400" />}
        />
        <StatCard
          label="Active Categories"
          value="7 Modules"
          subValue="Full Coverage"
          change="Task, Git, Policy..."
          changeType="neutral"
          icon={<Layers className="w-4 h-4 text-purple-400" />}
        />
      </div>

      {/* Filter and Search Bar */}
      <div className="space-y-3 bg-[#101012] p-3.5 border border-white/[0.08] rounded-[10px]">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Search Input */}
          <div className="relative flex-1 max-w-md">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search event name, agent, payload, or trace ID..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors"
            />
          </div>

          {/* Filter Pills */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Category Filter */}
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-mono text-[#6B6B6E] uppercase mr-1">Type:</span>
              {['all', 'Task', 'Pipeline', 'Agent', 'System', 'Git', 'Policy', 'Memory'].map((type) => (
                <button
                  key={type}
                  onClick={() => setSelectedType(type)}
                  className={`px-2 py-0.5 rounded-[4px] text-[11px] font-mono transition-colors cursor-pointer ${
                    selectedType.toLowerCase() === type.toLowerCase()
                      ? 'bg-[#FFB020] text-[#0A0A0B] font-bold'
                      : 'bg-[#141416] text-[#A8A8AB] hover:text-white border border-white/[0.08]'
                  }`}
                >
                  {type}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Severity & Status Secondary Filters */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-white/[0.06] text-xs font-mono">
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[#6B6B6E] uppercase flex items-center gap-1">
              <Filter size={12} /> Severity:
            </span>
            {['all', 'info', 'warning', 'error', 'critical'].map((sev) => (
              <button
                key={sev}
                onClick={() => setSelectedSeverity(sev)}
                className={`px-2 py-0.5 rounded text-[10px] uppercase transition-colors cursor-pointer ${
                  selectedSeverity === sev
                    ? 'bg-white/20 text-white font-bold border border-white/30'
                    : 'text-[#6B6B6E] hover:text-gray-300'
                }`}
              >
                {sev}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[10px] text-[#6B6B6E] uppercase">Status:</span>
            {['all', 'success', 'in_progress', 'failed'].map((st) => (
              <button
                key={st}
                onClick={() => setSelectedStatus(st)}
                className={`px-2 py-0.5 rounded text-[10px] uppercase transition-colors cursor-pointer ${
                  selectedStatus === st
                    ? 'bg-[#FFB020]/20 text-[#FFB020] border border-[#FFB020]/30 font-bold'
                    : 'text-[#6B6B6E] hover:text-gray-300'
                }`}
              >
                {st.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* View Mode Content */}
      {viewMode === 'list' && (
        <div className="space-y-2">
          {filtered.length === 0 ? (
            <div className="p-8 text-center bg-[#141416] border border-white/[0.08] rounded-[8px]">
              <ActivityIcon className="w-8 h-8 mx-auto text-gray-500 mb-2" />
              <p className="text-xs font-mono text-gray-400">No matching telemetry traces found</p>
            </div>
          ) : (
            filtered.map((log) => {
              const sevConfig = SEVERITY_COLORS[log.severity] || SEVERITY_COLORS.info;
              return (
                <div
                  key={log.id}
                  onClick={() => setSelectedLog(log)}
                  className={`p-3.5 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/40 rounded-[8px] transition-all cursor-pointer flex flex-col sm:flex-row sm:items-center justify-between gap-3 group ${sevConfig.bg}`}
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className={`w-2.5 h-2.5 rounded-full shrink-0 ${sevConfig.dot}`} />
                    <div className="min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">
                          {log.event}
                        </span>
                        <div className="flex items-center gap-1">
                          {getCategoryIcon(log.type)}
                          <span className="text-[10px] font-mono text-gray-300">{log.type}</span>
                        </div>
                        <span className={`px-1.5 py-0.2 text-[9px] font-mono uppercase rounded border ${sevConfig.text} ${sevConfig.border}`}>
                          {log.severity}
                        </span>
                      </div>
                      <p className="text-xs text-[#9C9C9F] truncate mt-1">{log.description}</p>
                    </div>
                  </div>

                  <div className="flex items-center gap-4 text-xs font-mono text-[#6B6B6E] shrink-0">
                    <span className="hidden md:inline text-[10px] bg-white/[0.04] px-2 py-0.5 rounded border border-white/[0.06]">
                      {log.latency_ms}ms
                    </span>
                    <span>Agent: <span className="text-[#FFB020] font-medium">{log.agent}</span></span>
                    <span>{log.time}</span>
                    <ChevronRight size={14} className="text-gray-500 group-hover:text-[#FFB020] transition-colors" />
                  </div>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Terminal View */}
      {viewMode === 'terminal' && (
        <div className="bg-[#0A0A0C] border border-white/[0.12] rounded-[10px] p-4 font-mono text-xs overflow-hidden shadow-2xl">
          <div className="flex items-center justify-between pb-3 border-b border-white/[0.08] mb-3">
            <div className="flex items-center gap-2">
              <div className="w-3 h-3 rounded-full bg-rose-500/80" />
              <div className="w-3 h-3 rounded-full bg-amber-500/80" />
              <div className="w-3 h-3 rounded-full bg-emerald-500/80" />
              <span className="text-xs text-gray-400 ml-2">nexus-telemetry-stream.log</span>
            </div>
            <span className="text-[10px] text-gray-500">{filtered.length} entries shown</span>
          </div>

          <div className="space-y-1.5 max-h-[500px] overflow-y-auto pr-2">
            {filtered.map((log) => (
              <div
                key={log.id}
                onClick={() => setSelectedLog(log)}
                className="hover:bg-white/[0.04] p-1.5 rounded cursor-pointer transition-colors flex items-start gap-2 text-[11px] leading-relaxed"
              >
                <span className="text-gray-500 select-none">[{log.time}]</span>
                <span className={`uppercase font-bold shrink-0 ${
                  log.severity === 'critical' ? 'text-red-400' :
                  log.severity === 'error' ? 'text-rose-400' :
                  log.severity === 'warning' ? 'text-amber-400' : 'text-blue-400'
                }`}>
                  [{log.severity}]
                </span>
                <span className="text-purple-400 shrink-0">[{log.type}]</span>
                <span className="text-amber-300 font-medium shrink-0">&lt;{log.agent}&gt;</span>
                <span className="text-gray-200 truncate flex-1">{log.event} - {log.description}</span>
                <span className="text-gray-500 select-none text-[10px]">{log.latency_ms}ms</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Analytics Dashboard View */}
      {viewMode === 'analytics' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Velocity Area Chart */}
            <div className="lg:col-span-2 bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
              <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-4 flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-[#FFB020]" />
                Event Velocity & Error Rate (Last 20 Mins)
              </h3>
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData}>
                    <XAxis dataKey="time" stroke="#6B6B6E" fontSize={10} />
                    <YAxis stroke="#6B6B6E" fontSize={10} />
                    <RechartsTooltip
                      contentStyle={{ backgroundColor: '#1C1C1F', borderColor: 'rgba(255,255,255,0.1)', borderRadius: '8px', fontSize: '11px' }}
                    />
                    <Area type="monotone" dataKey="events" name="Total Events" stroke="#FFB020" fill="#FFB020" fillOpacity={0.15} />
                    <Area type="monotone" dataKey="errors" name="Errors" stroke="#F43F5E" fill="#F43F5E" fillOpacity={0.2} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Severity Donut Chart */}
            <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4 flex flex-col justify-between">
              <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-2 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                Severity Breakdown
              </h3>
              <div className="h-48 relative">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={severityPieData} innerRadius={45} outerRadius={70} paddingAngle={4} dataKey="value">
                      {severityPieData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: '6px', fontSize: '11px' }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="grid grid-cols-2 gap-2 pt-2 border-t border-white/[0.06]">
                {severityPieData.map((item) => (
                  <div key={item.name} className="flex items-center gap-2 text-xs font-mono">
                    <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                    <span className="text-gray-400">{item.name}:</span>
                    <span className="text-white font-bold">{item.value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* Agent Activity Leaderboard */}
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-3 flex items-center gap-2">
              <Cpu className="w-4 h-4 text-blue-400" />
              Most Active Dispatching Agents
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
              {agentLeaderboard.map((item, idx) => (
                <div key={item.name} className="p-3 bg-[#141416] border border-white/[0.08] rounded-[6px]">
                  <div className="text-[10px] font-mono text-gray-500 uppercase">Rank #{idx + 1}</div>
                  <div className="text-xs font-medium text-white truncate mt-0.5">{item.name}</div>
                  <div className="text-sm font-bold text-[#FFB020] mt-1">{item.count} events</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Raw Trace Drawer */}
      <Drawer
        isOpen={!!selectedLog}
        onClose={() => setSelectedLog(null)}
        title={selectedLog?.event || 'Activity Detail'}
        subtitle={`Event Trace #${selectedLog?.id} · Type: ${selectedLog?.type}`}
      >
        {selectedLog && (
          <div className="space-y-4">
            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                Event Description
              </label>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs text-[#F2F1EE]">
                {selectedLog.description}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs font-mono">
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Dispatching Agent</div>
                <div className="text-[#FFB020] font-medium mt-1">{selectedLog.agent}</div>
              </div>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Status</div>
                <div className="text-[#22C55E] font-medium mt-1 uppercase">{selectedLog.status}</div>
              </div>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Severity</div>
                <div className="text-amber-400 font-medium mt-1 uppercase">{selectedLog.severity}</div>
              </div>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Latency</div>
                <div className="text-cyan-400 font-medium mt-1">{selectedLog.latency_ms} ms</div>
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[10px] font-mono text-[#6B6B6E] uppercase">
                  Raw Telemetry Payload (JSON)
                </label>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(JSON.stringify(selectedLog.raw_payload || selectedLog, null, 2));
                    setCopiedId(true);
                    setTimeout(() => setCopiedId(false), 2000);
                  }}
                  className="text-[10px] font-mono text-[#FFB020] hover:underline flex items-center gap-1 cursor-pointer"
                >
                  {copiedId ? <Check size={12} /> : <Copy size={12} />}
                  <span>{copiedId ? 'Copied!' : 'Copy JSON'}</span>
                </button>
              </div>
              <pre className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-[11px] font-mono text-[#A8A8AB] overflow-x-auto max-h-80">
                {JSON.stringify(
                  selectedLog.raw_payload || {
                    event_id: selectedLog.id,
                    type: selectedLog.type,
                    agent: selectedLog.agent,
                    severity: selectedLog.severity,
                    timestamp: selectedLog.time,
                    latency_ms: selectedLog.latency_ms,
                    exit_code: 0,
                  },
                  null,
                  2
                )}
              </pre>
            </div>
          </div>
        )}
      </Drawer>
    </div>
  );
}
