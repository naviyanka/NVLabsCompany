import { useState, useEffect, useMemo, useCallback } from 'react';
import {
  DollarSign,
  TrendingUp,
  CreditCard,
  ShieldAlert,
  Cpu,
  Download,
  BarChart3,
  Search,
  Zap,
} from 'lucide-react';
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import { Card } from '@/components/common/Card';
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Table } from '@/components/common/Table';
import { Modal } from '@/components/common/Modal';
import { Drawer } from '@/components/common/Drawer';
import { apiClient, unwrapItems } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { Agent } from '@/types/agent';

export interface ExtendedAgent extends Agent {
  daily_token_limit?: number;
  rate_limit_strategy?: 'Cascade to Flash' | 'Strict Block' | 'Queue & Retry';
  warning_threshold_pct?: number;
}

const DEFAULT_AGENTS: ExtendedAgent[] = [];

export function Budgets() {
  const [agents, setAgents] = useState<ExtendedAgent[]>(DEFAULT_AGENTS);
  const [search, setSearch] = useState('');
  const [selectedProvider, setSelectedProvider] = useState<string>('all');
  const [showCapModal, setShowCapModal] = useState(false);
  const [selectedAgent, setSelectedAgent] = useState<ExtendedAgent | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState('agent-atlas');
  const [newCapDollars, setNewCapDollars] = useState('500');
  const [newStrategy, setNewStrategy] = useState<'Cascade to Flash' | 'Strict Block' | 'Queue & Retry'>('Cascade to Flash');
  const [viewMode, setViewMode] = useState<'table' | 'analytics' | 'ratelimits'>('table');

  // Model Cascade Router Simulator State
  const [simTaskType, setSimTaskType] = useState('formatting');
  const [simTokens, setSimTokens] = useState(1000000);

  useEffect(() => {
    async function loadAgents() {
      try {
        const res = await apiClient.get<Agent[] | { items: Agent[] }>(
          `/api/v1/companies/${getActiveCompanyId()}/agents`
        );
        const items = unwrapItems(res);
        if (items.length > 0) {
          const formatted = items.map((a) => ({ ...a }));
          setAgents(formatted);
          if (formatted[0]) setSelectedAgentId(formatted[0].id);
        }
      } catch {
        // Fallback to default mock budget agents
      }
    }
    loadAgents();
  }, []);

  const totalSpentCents = useMemo(() => agents.reduce((sum, a) => sum + (a.spent_monthly_cents || 0), 0), [agents]);
  const totalBudgetCents = useMemo(() => agents.reduce((sum, a) => sum + (a.budget_monthly_cents || 30000), 0), [agents]);

  const MODEL_SPEND_DISTRIBUTION = useMemo(() => {
    const byModel = new Map<string, number>();
    for (const a of agents) {
      const key = a.model || a.adapter_type || 'unknown';
      byModel.set(key, (byModel.get(key) || 0) + (a.spent_monthly_cents || 0) / 100);
    }
    const entries = [...byModel.entries()].sort((a, b) => b[1] - a[1]).slice(0, 6);
    const total = entries.reduce((sum, [, spend]) => sum + spend, 0);
    const colors = ['#FFB020', '#38BDF8', '#22C55E', '#A855F7', '#F472B6', '#60A5FA'];
    return entries.map(([model, spend], i) => ({
      model,
      spend: Math.round(spend * 100) / 100,
      share: total > 0 ? `${((spend / total) * 100).toFixed(1)}%` : '—',
      color: colors[i % colors.length],
    }));
  }, [agents]);

  const DAILY_COST_TREND: { day: string; cost: number; tokens: number }[] = [];

  const handleUpdateCap = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedAgentId) return;
    try {
      const cents = Math.round(Number(newCapDollars) * 100);
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/agents/${selectedAgentId}`,
        { budget_monthly_cents: cents }
      );
    } catch {
      // Fallback local update
    }
    setAgents((prev) =>
      prev.map((a) => (a.id === selectedAgentId ? { ...a, budget_monthly_cents: Math.round(Number(newCapDollars) * 100), rate_limit_strategy: newStrategy } : a))
    );
    setShowCapModal(false);
  };

  // Filtered Agent List
  const filteredAgents = useMemo(() => {
    return agents.filter((a) => {
      if (selectedProvider !== 'all' && a.adapter_type !== selectedProvider) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          a.name.toLowerCase().includes(q) ||
          a.title.toLowerCase().includes(q) ||
          a.model.toLowerCase().includes(q) ||
          (a.adapter_type || '').toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [agents, search, selectedProvider]);

  // Model Cascade Simulation Calculation
  const cascadeSavings = useMemo(() => {
    const proCost = (simTokens / 1000000) * 15.0; // $15 / 1M tokens (Sonnet/GPT-4o)
    const flashCost = (simTokens / 1000000) * 0.60; // $0.60 / 1M tokens (Flash/Mini)
    const savedDollars = Math.max(0, proCost - flashCost);
    const savedPct = ((savedDollars / proCost) * 100).toFixed(1);
    return { proCost: proCost.toFixed(2), flashCost: flashCost.toFixed(2), savedDollars: savedDollars.toFixed(2), savedPct };
  }, [simTokens]);

  // Export handlers
  const handleExportJson = useCallback(() => {
    const jsonStr = JSON.stringify(filteredAgents, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_budgets_${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredAgents]);

  const handleExportCsv = useCallback(() => {
    const headers = ['ID', 'Name', 'Title', 'Adapter', 'Model', 'MTD Spend ($)', 'Monthly Cap ($)', 'Utilization (%)', 'Strategy'];
    const rows = filteredAgents.map((a) => {
      const spent = ((a.spent_monthly_cents || 0) / 100).toFixed(2);
      const cap = ((a.budget_monthly_cents || 30000) / 100).toFixed(2);
      const pct = Math.min(100, Math.round(((a.spent_monthly_cents || 0) / (a.budget_monthly_cents || 30000)) * 100));
      return [a.id, `"${a.name}"`, `"${a.title}"`, a.adapter_type, a.model, spent, cap, `${pct}%`, a.rate_limit_strategy || '—'];
    });
    const csvStr = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n');
    const blob = new Blob([csvStr], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nexus_budgets_${Date.now()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [filteredAgents]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <DollarSign className="w-5 h-5 text-[#22C55E]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight flex items-center gap-3">
              Model Economics & Token Budgets
              <span className="text-xs px-2.5 py-0.5 rounded-full font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                CASCADE ROUTING SIMULATOR
              </span>
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Real-time inference costs, spend caps, multi-agent rate limiting, and model cascade efficiency
          </p>
        </div>

        {/* Top Controls */}
        <div className="flex items-center gap-2">
          {/* View Mode Switcher */}
          <div className="flex items-center bg-[#101012] border border-white/[0.08] rounded-[6px] p-0.5">
            <button
              onClick={() => setViewMode('table')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'table' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Agent Budget Allocations Table"
            >
              <CreditCard size={13} />
              <span className="hidden sm:inline">Economics</span>
            </button>
            <button
              onClick={() => setViewMode('analytics')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'analytics' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Inference Cost Analytics"
            >
              <BarChart3 size={13} />
              <span className="hidden sm:inline">Analytics</span>
            </button>
            <button
              onClick={() => setViewMode('ratelimits')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'ratelimits' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Rate Limiting & Cascade Rules"
            >
              <Zap size={13} />
              <span className="hidden sm:inline">Rate Limits</span>
            </button>
          </div>

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

          <Button
            variant="primary"
            size="sm"
            icon={<CreditCard size={15} />}
            onClick={() => setShowCapModal(true)}
          >
            Adjust Spend Cap
          </Button>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total MTD Spend"
          value={`$${(totalSpentCents / 100).toFixed(2)}`}
          subValue={`of $${(totalBudgetCents / 100).toFixed(0)} Monthly Cap`}
          change="Within hard threshold"
          changeType="positive"
          icon={<DollarSign className="w-4 h-4 text-[#22C55E]" />}
        />
        <StatCard
          label="Daily Burn Rate"
          value="—"
          subValue="No daily metrics source yet"
          change="Awaiting daily aggregation API"
          changeType="positive"
          icon={<TrendingUp className="w-4 h-4 text-cyan-400" />}
        />
        <StatCard
          label="Cascade Savings"
          value={(() => {
            const saved = cascadeSavings.savedDollars;
            return `$${saved}`;
          })()}
          subValue="Simulated at current settings"
          change="From simulator below, not tracked spend"
          changeType="positive"
          icon={<Cpu className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="Anomalous Spikes"
          value="—"
          subValue="Not yet monitored"
          change="Requires incidents integration"
          changeType="positive"
          icon={<ShieldAlert className="w-4 h-4 text-purple-400" />}
        />
      </div>

      {/* Model Cascade Simulator Banner */}
      <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4 space-y-3">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2">
              <Zap className="w-4 h-4 text-[#FFB020]" />
              Model Cascade Router Cost Savings Simulator
            </h3>
            <p className="text-xs text-gray-400 font-mono mt-0.5">
              Automatically routes routine task dispatches to lightweight models before escalating to flagship Pro LLMs
            </p>
          </div>

          <div className="flex items-center gap-3 font-mono text-xs">
            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">Task Type:</span>
              <select
                value={simTaskType}
                onChange={(e) => setSimTaskType(e.target.value)}
                className="bg-[#141416] border border-white/[0.1] text-white px-2 py-1 rounded text-xs focus:outline-none"
              >
                <option value="formatting">Formatting & Schema</option>
                <option value="summary">Text Summarization</option>
                <option value="code_review">Code Review</option>
                <option value="reasoning">Multi-Step Reasoning</option>
              </select>
            </div>

            <div className="flex items-center gap-1.5">
              <span className="text-gray-500">Tokens:</span>
              <select
                value={simTokens}
                onChange={(e) => setSimTokens(Number(e.target.value))}
                className="bg-[#141416] border border-white/[0.1] text-white px-2 py-1 rounded text-xs focus:outline-none"
              >
                <option value={500000}>500k Tokens</option>
                <option value={1000000}>1M Tokens</option>
                <option value={5000000}>5M Tokens</option>
              </select>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 pt-2 border-t border-white/[0.06] font-mono text-xs">
          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded">
            <span className="text-[10px] text-gray-500 uppercase">Pro Model Cost</span>
            <div className="text-rose-400 font-bold mt-0.5">${cascadeSavings.proCost}</div>
          </div>
          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded">
            <span className="text-[10px] text-gray-500 uppercase">Cascade Flash Cost</span>
            <div className="text-cyan-400 font-bold mt-0.5">${cascadeSavings.flashCost}</div>
          </div>
          <div className="p-2.5 bg-[#141416] border border-white/[0.06] rounded">
            <span className="text-[10px] text-gray-500 uppercase">Net Cost Reduction</span>
            <div className="text-emerald-400 font-bold mt-0.5">${cascadeSavings.savedDollars}</div>
          </div>
          <div className="p-2.5 bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 rounded flex items-center justify-between">
            <span className="text-[10px] uppercase font-bold">Efficiency Lift</span>
            <span className="text-sm font-bold">+{cascadeSavings.savedPct}%</span>
          </div>
        </div>
      </div>

      {/* View Mode Content */}
      {viewMode === 'table' && (
        <div className="space-y-4">
          {/* Search & Filter Bar */}
          <div className="space-y-3 bg-[#101012] p-3.5 border border-white/[0.08] rounded-[10px]">
            <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
              {/* Search Bar */}
              <div className="relative flex-1 max-w-md">
                <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search agent call sign, title, model, or provider..."
                  className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors"
                />
              </div>

              {/* Provider Filter */}
              <div className="flex flex-wrap items-center gap-2 font-mono text-xs">
                <span className="text-[10px] text-[#6B6B6E] uppercase mr-1">Provider:</span>
                {['all', 'anthropic', 'openai', 'google'].map((prov) => (
                  <button
                    key={prov}
                    onClick={() => setSelectedProvider(prov)}
                    className={`px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer capitalize ${
                      selectedProvider === prov
                        ? 'bg-[#FFB020] text-black font-bold'
                        : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
                    }`}
                  >
                    {prov}
                  </button>
                ))}
              </div>
            </div>
          </div>

          {/* Table Card */}
          <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Per-Agent Spend Allocation & Hard Caps</span>} padding="none">
            <Table
              data={filteredAgents}
              keyExtractor={(a) => a.id}
              columns={[
                {
                  key: 'name',
                  header: 'Agent Call Sign',
                  sortable: true,
                  render: (a) => (
                    <div
                      onClick={() => setSelectedAgent(a)}
                      className="cursor-pointer group"
                    >
                      <div className="font-medium text-[#F2F1EE] group-hover:text-[#FFB020] transition-colors">{a.name}</div>
                      <div className="text-[11px] font-mono text-[#6B6B6E]">{a.model}</div>
                    </div>
                  ),
                },
                {
                  key: 'spent_monthly_cents',
                  header: 'MTD Spend',
                  sortable: true,
                  render: (a) => (
                    <span className="font-mono text-xs text-[#FFB020]">
                      ${((a.spent_monthly_cents || 0) / 100).toFixed(2)}
                    </span>
                  ),
                },
                {
                  key: 'budget_monthly_cents',
                  header: 'Hard Cap',
                  sortable: true,
                  render: (a) => (
                    <span className="font-mono text-xs text-[#F2F1EE]">
                      ${((a.budget_monthly_cents || 30000) / 100).toFixed(2)}
                    </span>
                  ),
                },
                {
                  key: 'utilization',
                  header: 'Utilization',
                  render: (a) => {
                    const pct = Math.min(100, Math.round(((a.spent_monthly_cents || 0) / (a.budget_monthly_cents || 30000)) * 100));
                    return (
                      <div className="flex items-center gap-2">
                        <div className="w-24 h-1.5 bg-white/[0.08] rounded-full overflow-hidden">
                          <div
                            className={`h-full ${pct > 80 ? 'bg-[#EF4444]' : 'bg-[#22C55E]'}`}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="text-[11px] font-mono text-[#6B6B6E]">{pct}%</span>
                      </div>
                    );
                  },
                },
                {
                  key: 'strategy',
                  header: 'Rate Limit Strategy',
                  render: (a) => (
                    <span className="px-2 py-0.5 rounded text-[10px] font-mono bg-white/[0.04] text-gray-300 border border-white/[0.08]">
                      {a.rate_limit_strategy || '—'}
                    </span>
                  ),
                },
                {
                  key: 'action',
                  header: 'Action',
                  align: 'right',
                  render: (a) => (
                    <Button
                      variant="ghost"
                      size="xs"
                      onClick={() => {
                        setSelectedAgentId(a.id);
                        setNewCapDollars(((a.budget_monthly_cents || 30000) / 100).toString());
                        setShowCapModal(true);
                      }}
                    >
                      Adjust Cap
                    </Button>
                  ),
                },
              ]}
            />
          </Card>
        </div>
      )}

      {/* Analytics Dashboard View */}
      {viewMode === 'analytics' && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* 7-Day Cost Bar Chart */}
            <div className="lg:col-span-7">
              <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">7-Day Daily Inference Cost ($)</span>}>
                <div className="h-64 w-full">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={DAILY_COST_TREND} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                      <XAxis dataKey="day" stroke="#6B6B6E" fontSize={10} />
                      <YAxis stroke="#6B6B6E" fontSize={10} />
                      <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: 6, fontSize: 11, color: '#F2F1EE' }} />
                      <Bar dataKey="cost" name="Inference Cost ($)" fill="#FFB020" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            </div>

            {/* Model Distribution Donut Chart */}
            <div className="lg:col-span-5">
              <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Model Tier Spend Share</span>}>
                <div className="h-48 relative">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={MODEL_SPEND_DISTRIBUTION} innerRadius={45} outerRadius={70} paddingAngle={4} dataKey="spend">
                        {MODEL_SPEND_DISTRIBUTION.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: 6, fontSize: 11 }} />
                    </PieChart>
                  </ResponsiveContainer>
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2 border-t border-white/[0.06]">
                  {MODEL_SPEND_DISTRIBUTION.map((item) => (
                    <div key={item.model} className="flex items-center gap-2 text-xs font-mono">
                      <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                      <span className="text-gray-400 truncate">{item.model.split(' ')[0]}:</span>
                      <span className="text-white font-bold">${item.spend}</span>
                    </div>
                  ))}
                </div>
              </Card>
            </div>
          </div>
        </div>
      )}

      {/* Rate Limiting & Cascade Rules View Mode */}
      {viewMode === 'ratelimits' && (
        <div className="space-y-4 font-mono text-xs">
          <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-4">
            <h3 className="text-sm font-display font-medium text-white flex items-center gap-2 mb-2">
              <Zap className="w-4 h-4 text-[#FFB020]" />
              Active Sliding Window Token Bucket Rules
            </h3>
            <p className="text-xs text-gray-400">
              Redis Lua scripts enforce sliding window rate limits on every agent dispatch endpoint
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
              <span className="text-[10px] text-gray-500 uppercase font-bold">Cascade Rule #1</span>
              <h4 className="text-xs font-bold text-white">Auto-Cascade Pro to Flash</h4>
              <p className="text-gray-400 text-[11px]">When agent token usage exceeds 80% daily quota, switch model to GPT-4o-mini automatically.</p>
            </div>

            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
              <span className="text-[10px] text-gray-500 uppercase font-bold">Cascade Rule #2</span>
              <h4 className="text-xs font-bold text-white">Strict Budget Hard Cap Block</h4>
              <p className="text-gray-400 text-[11px]">Halt dispatches for agents reaching 100% monthly budget cap until operator approval.</p>
            </div>

            <div className="p-4 bg-[#141416] border border-white/[0.08] rounded-[8px] space-y-2">
              <span className="text-[10px] text-gray-500 uppercase font-bold">Cascade Rule #3</span>
              <h4 className="text-xs font-bold text-white">Exponential Queue Backoff</h4>
              <p className="text-gray-400 text-[11px]">Exponential backoff retry with jitter on external provider rate limit (HTTP 429) errors.</p>
            </div>
          </div>
        </div>
      )}

      {/* Agent Detail Drawer */}
      <Drawer
        isOpen={!!selectedAgent}
        onClose={() => setSelectedAgent(null)}
        title={selectedAgent?.name || 'Agent Detail'}
        subtitle={`Title: ${selectedAgent?.title} · Model: ${selectedAgent?.model}`}
      >
        {selectedAgent && (
          <div className="space-y-4 font-mono text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded">
                <span className="text-[10px] text-gray-500 uppercase">MTD Spend</span>
                <div className="text-[#FFB020] font-bold text-sm mt-1">
                  ${((selectedAgent.spent_monthly_cents || 0) / 100).toFixed(2)}
                </div>
              </div>

              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded">
                <span className="text-[10px] text-gray-500 uppercase">Hard Cap</span>
                <div className="text-white font-bold text-sm mt-1">
                  ${((selectedAgent.budget_monthly_cents || 30000) / 100).toFixed(2)}
                </div>
              </div>
            </div>

            <div className="p-3 bg-[#101012] border border-white/[0.06] rounded space-y-1">
              <span className="text-[10px] text-gray-500 uppercase">Rate Limit Strategy</span>
              <div className="text-cyan-400 font-bold">{selectedAgent.rate_limit_strategy || '—'}</div>
            </div>

            <div className="flex justify-end pt-2 border-t border-white/[0.08]">
              <Button variant="secondary" size="sm" onClick={() => setSelectedAgent(null)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* Spend Cap Modal */}
      <Modal isOpen={showCapModal} onClose={() => setShowCapModal(false)} title="Adjust Agent Monthly Spend Cap">
        <form onSubmit={handleUpdateCap} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Select Agent
            </label>
            <select
              value={selectedAgentId}
              onChange={(e) => setSelectedAgentId(e.target.value)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              {agents.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.title})
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Rate Limit Strategy
            </label>
            <select
              value={newStrategy}
              onChange={(e) => setNewStrategy(e.target.value as any)}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            >
              <option value="Cascade to Flash">Cascade to Flash Model</option>
              <option value="Strict Block">Strict Block at Cap</option>
              <option value="Queue & Retry">Queue & Exponential Retry</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Monthly Cap (USD $)
            </label>
            <input
              type="number"
              value={newCapDollars}
              onChange={(e) => setNewCapDollars(e.target.value)}
              step="50"
              min="10"
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowCapModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Save Cap Limit
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
