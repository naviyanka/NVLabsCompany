import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Brain,
  Database,
  Search,
  Plus,
  Sparkles,
  Share2,
  Users,
  BarChart3,
  Trash2,
  ChevronRight,
  Sliders,
  AlertTriangle,
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
import { StatCard } from '@/components/common/StatCard';
import { Button } from '@/components/common/Button';
import { Modal } from '@/components/common/Modal';
import { Drawer } from '@/components/common/Drawer';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import { listAgents } from '@/api/agents';
import type { Agent } from '@/types/agent';

export interface MemoryRecord {
  id: string;
  agent_id: string | null;
  scope: string;
  content: string;
  importance: number;
  access_count: number;
  tier: string;
  created_at: string;
}

interface MemoryStats {
  total: number;
  by_tier: Record<string, number>;
  by_scope: Record<string, number>;
  avg_importance: number;
  agents_with_memory: number;
}

interface MemoryHealth {
  stale_count: number;
  low_relevance_count: number;
  duplicates_estimate: number;
}

const SCOPE_COLORS: Record<string, string> = {
  task_context: 'bg-[#FFB020]/15 text-[#FFB020] border-[#FFB020]/30',
  long_term: 'bg-[#38BDF8]/15 text-[#38BDF8] border-[#38BDF8]/30',
  guidelines: 'bg-[#22C55E]/15 text-[#22C55E] border-[#22C55E]/30',
  episodic_reflection: 'bg-[#A855F7]/15 text-[#A855F7] border-[#A855F7]/30',
  system_rule: 'bg-[#F43F5E]/15 text-[#F43F5E] border-[#F43F5E]/30',
  agent: 'bg-white/10 text-gray-300 border-white/20',
};

const TIER_COLORS: Record<string, string> = {
  hot: 'text-rose-400',
  warm: 'text-[#FFB020]',
  cold: 'text-[#6B6B6E]',
};

export function Memory() {
  const navigate = useNavigate();
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [health, setHealth] = useState<MemoryHealth | null>(null);
  const [search, setSearch] = useState('');
  const [selectedScope, setSelectedScope] = useState<string>('all');
  const [selectedAgent, setSelectedAgent] = useState<string>('all');
  const [minImportance, setMinImportance] = useState<number>(0);
  const [selectedMemory, setSelectedMemory] = useState<MemoryRecord | null>(null);
  const [showModal, setShowModal] = useState(false);
  const [viewMode, setViewMode] = useState<'list' | 'table' | 'analytics'>('list');
  const [loading, setLoading] = useState(true);

  // New Memory Form
  const [newAgentId, setNewAgentId] = useState('');
  const [newScope, setNewScope] = useState('task_context');
  const [newContent, setNewContent] = useState('');
  const [newImportance, setNewImportance] = useState(0.85);

  const agentMap = useMemo(() => {
    const map: Record<string, Agent> = {};
    agents.forEach((a) => { map[a.id] = a; });
    return map;
  }, [agents]);

  const agentLabel = useCallback(
    (agentId: string | null) => {
      if (!agentId) return 'Company-wide';
      return agentMap[agentId]?.name || agentId;
    },
    [agentMap]
  );

  const loadAll = useCallback(async () => {
    setLoading(true);
    const companyId = getActiveCompanyId();
    try {
      const [memRes, agentsRes, statsRes, healthRes] = await Promise.all([
        apiClient.get<MemoryRecord[]>(`/api/v1/companies/${companyId}/memory`),
        listAgents(),
        apiClient.get<MemoryStats>(`/api/v1/companies/${companyId}/memory/stats`),
        apiClient.get<MemoryHealth>(`/api/v1/companies/${companyId}/memory/health`),
      ]);
      setMemories(memRes);
      setAgents(agentsRes);
      setStats(statsRes);
      setHealth(healthRes);
      if (!newAgentId && agentsRes.length > 0) setNewAgentId(agentsRes[0]?.id ?? '');
    } catch {
      // Leave existing state as-is; the page will show its empty states.
    } finally {
      setLoading(false);
    }
  }, [newAgentId]);

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCreateMemory = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newContent.trim() || !newAgentId) return;
    const created = await apiClient.post<MemoryRecord>(
      `/api/v1/agents/${newAgentId}/memory`,
      {
        scope: newScope,
        content: newContent,
        importance: Number(newImportance),
      }
    );
    setMemories((prev) => [created, ...prev]);
    setShowModal(false);
    setNewContent('');
  };

  const handleDeleteMemory = useCallback(async (id: string) => {
    await apiClient.delete(`/api/v1/memory/${id}`);
    setMemories((prev) => prev.filter((m) => m.id !== id));
    setSelectedMemory((prev) => (prev?.id === id ? null : prev));
  }, []);

  // Distinct agents that actually have memories, for the filter row
  const agentFilterList = useMemo(() => {
    const ids = new Set<string>();
    memories.forEach((m) => { if (m.agent_id) ids.add(m.agent_id); });
    return Array.from(ids);
  }, [memories]);

  const filtered = useMemo(() => {
    return memories.filter((m) => {
      if (selectedScope !== 'all' && m.scope !== selectedScope) return false;
      if (selectedAgent !== 'all' && m.agent_id !== selectedAgent) return false;
      if (m.importance < minImportance) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (
          m.content.toLowerCase().includes(q) ||
          agentLabel(m.agent_id).toLowerCase().includes(q) ||
          m.scope.toLowerCase().includes(q) ||
          m.id.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [memories, search, selectedScope, selectedAgent, minImportance, agentLabel]);

  const importanceDistChartData = useMemo(() => {
    const high = memories.filter((m) => m.importance >= 0.85).length;
    const med = memories.filter((m) => m.importance >= 0.6 && m.importance < 0.85).length;
    const low = memories.filter((m) => m.importance < 0.6).length;
    return [
      { name: 'High Importance (≥85%)', value: high, color: '#22C55E' },
      { name: 'Medium Importance (60-84%)', value: med, color: '#FFB020' },
      { name: 'Low Importance (<60%)', value: low, color: '#F43F5E' },
    ];
  }, [memories]);

  const agentMemoryChartData = useMemo(() => {
    const counts: Record<string, number> = {};
    memories.forEach((m) => {
      const label = agentLabel(m.agent_id);
      counts[label] = (counts[label] || 0) + 1;
    });
    return Object.entries(counts).map(([name, count]) => ({ name, count }));
  }, [memories, agentLabel]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 pb-4 border-b border-white/[0.08]">
        <div>
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-[#FFB020]" />
            <h1 className="text-xl font-display font-medium text-[#F2F1EE] tracking-tight">
              Agent Memory
            </h1>
          </div>
          <p className="text-xs font-mono text-[#6B6B6E] mt-1">
            Long-term and task context memories stored per agent and company-wide
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {/* View Mode Switcher */}
          <div className="flex items-center bg-[#101012] border border-white/[0.08] rounded-[6px] p-0.5">
            <button
              onClick={() => setViewMode('list')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'list' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Memory Cards"
            >
              <Brain size={13} />
              <span className="hidden sm:inline">Cards</span>
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'table' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Memory Table"
            >
              <Database size={13} />
              <span className="hidden sm:inline">Table</span>
            </button>
            <button
              onClick={() => setViewMode('analytics')}
              className={`px-2.5 py-1 rounded-[4px] text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer ${
                viewMode === 'analytics' ? 'bg-[#FFB020] text-black font-semibold' : 'text-gray-400 hover:text-white'
              }`}
              title="Memory Analytics"
            >
              <BarChart3 size={13} />
              <span className="hidden sm:inline">Analytics</span>
            </button>
          </div>

          <Button
            variant="secondary"
            size="sm"
            icon={<Share2 size={14} className="text-[#FFB020]" />}
            onClick={() => navigate('/memory-graph')}
          >
            Visual Memory Graph
          </Button>

          <Button
            variant="primary"
            size="sm"
            icon={<Plus size={15} />}
            onClick={() => setShowModal(true)}
            disabled={agents.length === 0}
          >
            Record Memory
          </Button>
        </div>
      </div>

      {/* Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Memory Entries"
          value={stats?.total ?? memories.length}
          subValue="Across all tiers"
          icon={<Database className="w-4 h-4 text-[#FFB020]" />}
        />
        <StatCard
          label="Avg Importance Weight"
          value={`${Math.round((stats?.avg_importance ?? 0) * 100)}%`}
          subValue="Cross-session priority"
          icon={<Sparkles className="w-4 h-4 text-emerald-400" />}
        />
        <StatCard
          label="Agents With Memory"
          value={stats?.agents_with_memory ?? 0}
          subValue={`of ${agents.length} total agents`}
          icon={<Users className="w-4 h-4 text-cyan-400" />}
        />
        <StatCard
          label="Stale Entries (>90d)"
          value={health?.stale_count ?? 0}
          subValue={`${health?.low_relevance_count ?? 0} low relevance`}
          changeType={health && health.stale_count > 0 ? 'negative' : 'neutral'}
          icon={<AlertTriangle className="w-4 h-4 text-amber-400" />}
        />
      </div>

      {/* Filters & Search Control Bar */}
      <div className="space-y-3 bg-[#101012] p-3.5 border border-white/[0.08] rounded-[10px]">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Search Input */}
          <div className="relative flex-1 max-w-md">
            <Search className="w-3.5 h-3.5 text-[#6B6B6E] absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search memory text, agent, id, or scope..."
              className="w-full pl-8 pr-3 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] placeholder-[#6B6B6E] focus:outline-none focus:border-[#FFB020] transition-colors"
            />
          </div>

          {/* Scope Filters */}
          <div className="flex flex-wrap items-center gap-1.5">
            {['all', 'task_context', 'long_term', 'guidelines', 'episodic_reflection', 'system_rule', 'agent'].map((scope) => (
              <button
                key={scope}
                onClick={() => setSelectedScope(scope)}
                className={`px-2.5 py-1 rounded-[4px] text-xs font-mono transition-colors cursor-pointer capitalize ${
                  selectedScope === scope
                    ? 'bg-[#FFB020] text-[#0A0A0B] font-bold'
                    : 'bg-[#141416] text-[#6B6B6E] hover:text-[#F2F1EE] border border-white/[0.08]'
                }`}
              >
                {scope.replace('_', ' ')}
              </button>
            ))}
          </div>
        </div>

        {/* Secondary Filter: Agent & Importance Threshold Slider */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2.5 border-t border-white/[0.06] text-xs font-mono">
          {/* Agent Filter */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] text-[#6B6B6E] uppercase flex items-center gap-1">
              <Users size={12} /> Agent:
            </span>
            <button
              onClick={() => setSelectedAgent('all')}
              className={`px-2 py-0.5 rounded text-[10px] transition-colors cursor-pointer ${
                selectedAgent === 'all' ? 'bg-white/20 text-white font-bold' : 'text-[#6B6B6E] hover:text-gray-300'
              }`}
            >
              All Agents
            </button>
            {agentFilterList.map((agentId) => (
              <button
                key={agentId}
                onClick={() => setSelectedAgent(agentId)}
                className={`px-2 py-0.5 rounded text-[10px] transition-colors cursor-pointer ${
                  selectedAgent === agentId
                    ? 'bg-[#FFB020]/20 text-[#FFB020] border border-[#FFB020]/30 font-bold'
                    : 'text-[#6B6B6E] hover:text-gray-300'
                }`}
              >
                {agentLabel(agentId).split(' ')[0]}
              </button>
            ))}
          </div>

          {/* Importance Weight Threshold Slider */}
          <div className="flex items-center gap-2">
            <Sliders size={12} className="text-[#FFB020]" />
            <span className="text-[10px] text-[#6B6B6E] uppercase">Min Importance:</span>
            <input
              type="range"
              min="0"
              max="0.9"
              step="0.1"
              value={minImportance}
              onChange={(e) => setMinImportance(parseFloat(e.target.value))}
              className="w-24 accent-[#FFB020] cursor-pointer"
            />
            <span className="text-xs text-[#FFB020] font-bold min-w-[36px]">
              {(minImportance * 100).toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="p-8 text-center bg-[#141416] border border-white/[0.08] rounded-[8px]">
          <p className="text-xs font-mono text-gray-400">Loading memories…</p>
        </div>
      ) : (
        <>
          {/* View Mode Content */}
          {viewMode === 'list' && (
            <div className="space-y-3">
              {filtered.length === 0 ? (
                <div className="p-8 text-center bg-[#141416] border border-white/[0.08] rounded-[8px]">
                  <Brain className="w-8 h-8 mx-auto text-gray-500 mb-2" />
                  <p className="text-xs font-mono text-gray-400">No matching memory entries found</p>
                </div>
              ) : (
                filtered.map((mem) => {
                  const scopeBadgeStyle = SCOPE_COLORS[mem.scope] || 'bg-white/10 text-gray-300 border-white/20';
                  const importancePct = Math.round(mem.importance * 100);

                  return (
                    <div
                      key={mem.id}
                      onClick={() => setSelectedMemory(mem)}
                      className="p-4 bg-[#141416] border border-white/[0.08] hover:border-[#FFB020]/40 rounded-[10px] transition-all cursor-pointer group flex flex-col justify-between"
                    >
                      <div className="space-y-2">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-2 text-xs font-mono">
                            <span className={`px-2 py-0.5 text-[10px] font-bold rounded border uppercase ${scopeBadgeStyle}`}>
                              {mem.scope.replace('_', ' ')}
                            </span>
                            <span className="text-[#6B6B6E]">·</span>
                            <span className="text-white font-medium">Agent: <span className="text-[#FFB020]">{agentLabel(mem.agent_id)}</span></span>
                          </div>

                          {/* Importance Bar */}
                          <div className="flex items-center gap-2">
                            <div className="w-24 h-2 bg-[#0A0A0C] rounded-full overflow-hidden border border-white/[0.08]">
                              <div
                                className={`h-full transition-all ${
                                  importancePct >= 85 ? 'bg-emerald-500' : importancePct >= 60 ? 'bg-[#FFB020]' : 'bg-rose-500'
                                }`}
                                style={{ width: `${importancePct}%` }}
                              />
                            </div>
                            <span className="text-[11px] font-mono font-bold text-emerald-400 min-w-[45px] text-right">
                              {importancePct}% Weight
                            </span>
                          </div>
                        </div>

                        <p className="text-xs text-[#F2F1EE] font-sans leading-relaxed pt-1">
                          {mem.content}
                        </p>
                      </div>

                      <div className="mt-3 pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[10px] font-mono text-[#6B6B6E]">
                        <div className="flex items-center gap-3">
                          <span>ID: <strong className="text-gray-300">{mem.id.slice(0, 8)}</strong></span>
                          <span>·</span>
                          <span className={TIER_COLORS[mem.tier] || ''}>Tier: {mem.tier}</span>
                          <span>·</span>
                          <span>Accessed: {mem.access_count}x</span>
                        </div>
                        <span className="text-[#FFB020] group-hover:underline flex items-center gap-1 font-medium">
                          Inspect <ChevronRight size={12} />
                        </span>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          )}

          {/* Table View */}
          {viewMode === 'table' && (
            <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] overflow-hidden shadow-2xl">
              <div className="p-3.5 border-b border-white/[0.08] flex items-center justify-between bg-[#141416]">
                <span className="text-xs font-mono text-gray-300 font-bold">Memory Records</span>
                <span className="text-[10px] font-mono text-gray-500">{filtered.length} Entries</span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-xs font-mono">
                  <thead>
                    <tr className="bg-[#0A0A0C] border-b border-white/[0.08] text-gray-400 text-[10px] uppercase">
                      <th className="p-3">ID</th>
                      <th className="p-3">Scope</th>
                      <th className="p-3">Agent</th>
                      <th className="p-3">Importance</th>
                      <th className="p-3">Tier</th>
                      <th className="p-3">Access Count</th>
                      <th className="p-3 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/[0.04] text-gray-300">
                    {filtered.map((mem) => (
                      <tr key={mem.id} className="hover:bg-white/[0.04] transition-colors">
                        <td className="p-3 font-bold text-[#FFB020]">{mem.id.slice(0, 8)}</td>
                        <td className="p-3">
                          <span className="px-1.5 py-0.5 rounded text-[9px] uppercase border bg-white/[0.04] border-white/[0.08]">
                            {mem.scope}
                          </span>
                        </td>
                        <td className="p-3 text-white">{agentLabel(mem.agent_id)}</td>
                        <td className="p-3 text-emerald-400 font-bold">{(mem.importance * 100).toFixed(0)}%</td>
                        <td className={`p-3 ${TIER_COLORS[mem.tier] || 'text-gray-400'}`}>{mem.tier}</td>
                        <td className="p-3 text-gray-400">{mem.access_count}</td>
                        <td className="p-3 text-right">
                          <button
                            onClick={() => setSelectedMemory(mem)}
                            className="px-2 py-1 bg-white/[0.06] hover:bg-white/[0.1] text-[#FFB020] rounded text-[10px] transition-colors cursor-pointer"
                          >
                            View
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Analytics Dashboard View */}
          {viewMode === 'analytics' && (
            <div className="space-y-6">
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Importance Distribution Chart */}
                <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-5">
                  <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-4 flex items-center gap-2">
                    <BarChart3 className="w-4 h-4 text-[#FFB020]" />
                    Memory Importance Weight Distribution
                  </h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie data={importanceDistChartData} innerRadius={50} outerRadius={80} paddingAngle={4} dataKey="value">
                          {importanceDistChartData.map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.color} />
                          ))}
                        </Pie>
                        <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: '8px', fontSize: '11px' }} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                </div>

                {/* Agent Memory Breakdown Chart */}
                <div className="bg-[#101012] border border-white/[0.08] rounded-[10px] p-5">
                  <h3 className="text-sm font-display font-medium text-[#F2F1EE] mb-4 flex items-center gap-2">
                    <Users className="w-4 h-4 text-blue-400" />
                    Memories Stored per Agent
                  </h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={agentMemoryChartData}>
                        <XAxis dataKey="name" stroke="#6B6B6E" fontSize={10} />
                        <YAxis stroke="#6B6B6E" fontSize={10} />
                        <RechartsTooltip contentStyle={{ backgroundColor: '#1C1C1F', borderRadius: '8px', fontSize: '11px' }} />
                        <Bar dataKey="count" name="Memories" fill="#38BDF8" radius={[4, 4, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </div>
            </div>
          )}
        </>
      )}

      {/* Memory Inspection Drawer */}
      <Drawer
        isOpen={!!selectedMemory}
        onClose={() => setSelectedMemory(null)}
        title={`Memory Record`}
        subtitle={selectedMemory ? `Scope: ${selectedMemory.scope} · Agent: ${agentLabel(selectedMemory.agent_id)}` : ''}
      >
        {selectedMemory && (
          <div className="space-y-4">
            <div>
              <label className="text-[10px] font-mono text-[#6B6B6E] uppercase block mb-1">
                Memory Content Text
              </label>
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] text-xs text-[#F2F1EE] leading-relaxed">
                {selectedMemory.content}
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3 text-xs font-mono">
              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Importance</div>
                <div className="text-emerald-400 font-bold text-sm mt-1">
                  {(selectedMemory.importance * 100).toFixed(0)}%
                </div>
              </div>

              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Tier</div>
                <div className={`font-bold text-sm mt-1 ${TIER_COLORS[selectedMemory.tier] || 'text-gray-300'}`}>
                  {selectedMemory.tier}
                </div>
              </div>

              <div className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px]">
                <div className="text-[10px] text-[#6B6B6E] uppercase">Access Count</div>
                <div className="text-cyan-400 font-bold text-sm mt-1">
                  {selectedMemory.access_count}
                </div>
              </div>
            </div>

            <div className="text-[10px] font-mono text-[#6B6B6E]">
              Created {new Date(selectedMemory.created_at).toLocaleString()}
            </div>

            {/* Drawer Actions */}
            <div className="pt-3 border-t border-white/[0.08] flex items-center justify-between">
              <button
                onClick={() => handleDeleteMemory(selectedMemory.id)}
                className="px-3 py-1.5 bg-rose-500/10 hover:bg-rose-500/20 text-rose-400 border border-rose-500/30 rounded text-xs font-mono flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <Trash2 size={13} />
                <span>Delete Memory</span>
              </button>

              <Button variant="secondary" size="sm" onClick={() => setSelectedMemory(null)}>
                Close
              </Button>
            </div>
          </div>
        )}
      </Drawer>

      {/* Record Memory Modal */}
      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title="Record Memory">
        <form onSubmit={handleCreateMemory} className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
                Target Agent
              </label>
              <select
                value={newAgentId}
                onChange={(e) => setNewAgentId(e.target.value)}
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
                Memory Scope
              </label>
              <select
                value={newScope}
                onChange={(e) => setNewScope(e.target.value)}
                className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              >
                <option value="task_context">Task Context</option>
                <option value="long_term">Long-Term Knowledge</option>
                <option value="guidelines">Policy & Guidelines</option>
                <option value="episodic_reflection">Episodic Reflection</option>
                <option value="system_rule">System Rule</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Importance Weight (0.1 to 1.0)
            </label>
            <input
              type="number"
              step="0.05"
              min="0.1"
              max="1.0"
              value={newImportance}
              onChange={(e) => setNewImportance(parseFloat(e.target.value))}
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-xs font-mono text-[#A8A8AB] uppercase mb-1">
              Memory Content Text
            </label>
            <textarea
              value={newContent}
              onChange={(e) => setNewContent(e.target.value)}
              rows={4}
              placeholder="e.g. Always enforce multi-tenant company isolation headers on every API response..."
              className="w-full px-3 py-2 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
              required
            />
          </div>

          <div className="flex justify-end gap-2 pt-2 border-t border-white/[0.08]">
            <Button variant="secondary" size="sm" type="button" onClick={() => setShowModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" size="sm" type="submit">
              Store Memory
            </Button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
