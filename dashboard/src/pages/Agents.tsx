import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '@/hooks/useApi';
import { agentsApi } from '@/api/agents';
import { apiClient } from '@/api/client';
import type { Agent, AgentCreateRequest } from '@/types/agent';
import { COMPANY_ID } from '@/config';
import {
  UserPlus,
  Search,
  Cpu,
  Activity,
  Zap,
  Coffee,
  AlertTriangle,
  WifiOff,
  ChevronRight,
  X,
  Play,
  Pause,
  Trash2,
} from 'lucide-react';

const STATUS_CONFIG: Record<string, { label: string; color: string; bg: string; icon: any }> = {
  idle: { label: 'Idle', color: '#3B82F6', bg: 'bg-blue-500/10', icon: Coffee },
  ready: { label: 'Ready', color: '#22C55E', bg: 'bg-green-500/10', icon: Zap },
  executing: { label: 'Working', color: '#22C55E', bg: 'bg-green-500/10', icon: Activity },
  paused: { label: 'Paused', color: '#EAB308', bg: 'bg-yellow-500/10', icon: Coffee },
  error: { label: 'Error', color: '#EF4444', bg: 'bg-red-500/10', icon: AlertTriangle },
  terminated: { label: 'Offline', color: '#64748B', bg: 'bg-gray-500/10', icon: WifiOff },
};

export function Agents() {
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const navigate = useNavigate();

  const { data: agents, loading, error, refetch } = useApi<Agent[]>(
    () => agentsApi.list(COMPANY_ID, { page_size: 50 }),
    [COMPANY_ID],
  );

  const filteredAgents = (agents ?? []).filter((agent) => {
    const matchesSearch =
      !searchQuery ||
      agent.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      agent.role.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesStatus = statusFilter === 'all' || agent.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  const statusCounts = (agents ?? []).reduce(
    (acc, a) => {
      acc[a.status] = (acc[a.status] || 0) + 1;
      acc.total++;
      return acc;
    },
    { total: 0 } as Record<string, number>,
  );

  const handleWake = useCallback(async (agentId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setActionLoading(agentId);
    try {
      await agentsApi.wake(agentId);
      refetch();
    } catch (err) {
      console.error('Wake failed:', err);
    } finally {
      setActionLoading(null);
    }
  }, [refetch]);

  const handlePause = useCallback(async (agentId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setActionLoading(agentId);
    try {
      await agentsApi.pause(agentId);
      refetch();
    } catch (err) {
      console.error('Pause failed:', err);
    } finally {
      setActionLoading(null);
    }
  }, [refetch]);

  const handleDelete = useCallback(async (agentId: string, agentName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm(`Delete agent "${agentName}"? This cannot be undone.`)) return;
    setActionLoading(agentId);
    try {
      await agentsApi.delete(agentId);
      refetch();
    } catch (err) {
      console.error('Delete failed:', err);
    } finally {
      setActionLoading(null);
    }
  }, [refetch]);

  const handleCreateAgent = useCallback(async (formData: AgentCreateRequest) => {
    try {
      await agentsApi.create(COMPANY_ID, formData);
      setShowCreateModal(false);
      refetch();
    } catch (err) {
      throw err;
    }
  }, [refetch]);

  if (error) {
    return (
      <div className="p-8 text-center">
        <AlertTriangle size={32} className="mx-auto text-red-400 mb-3" />
        <p className="text-white font-medium">Failed to load agents</p>
        <p className="text-sm text-gray-400 mt-1">{error}</p>
        <button onClick={refetch} className="mt-3 text-sm text-primary-400 hover:text-primary-300">
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Agents</h1>
          <p className="text-sm text-gray-400 mt-1">
            {statusCounts.total || 0} agents in your workforce
          </p>
        </div>
        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-2 px-4 py-2 bg-green-500/20 text-green-400 text-sm font-medium rounded-lg hover:bg-green-500/30 transition-colors"
        >
          <UserPlus size={16} />
          Hire Agent
        </button>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { label: 'Total', value: statusCounts.total || 0, color: '#8B5CF6' },
          { label: 'Working', value: statusCounts.executing || statusCounts.ready || 0, color: '#22C55E' },
          { label: 'Idle', value: statusCounts.idle || 0, color: '#3B82F6' },
          { label: 'Paused', value: statusCounts.paused || 0, color: '#EAB308' },
          { label: 'Error', value: statusCounts.error || 0, color: '#EF4444' },
        ].map((stat) => (
          <div key={stat.label} className="p-3 rounded-lg bg-white/[0.03] border border-white/[0.06]">
            <p className="text-xs text-gray-400">{stat.label}</p>
            <p className="text-xl font-bold mt-1" style={{ color: stat.color }}>
              {stat.value}
            </p>
          </div>
        ))}
      </div>

      {/* Search & Filter */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder="Search agents by name or role..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-dark-bg border border-white/[0.08] rounded-lg pl-9 pr-3 py-2 text-white text-sm placeholder-gray-500 focus:outline-none focus:border-primary-500"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-gray-300 focus:outline-none focus:border-primary-500"
        >
          <option value="all">All Status</option>
          <option value="idle">Idle</option>
          <option value="ready">Ready</option>
          <option value="executing">Working</option>
          <option value="paused">Paused</option>
          <option value="error">Error</option>
        </select>
      </div>

      {/* Agent Grid */}
      {loading ? (
        <div className="flex justify-center py-12">
          <div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredAgents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onClick={() => navigate(`/agents/${agent.id}`)}
              onWake={(e) => handleWake(agent.id, e)}
              onPause={(e) => handlePause(agent.id, e)}
              onDelete={(e) => handleDelete(agent.id, agent.name, e)}
              actionLoading={actionLoading === agent.id}
            />
          ))}
          {filteredAgents.length === 0 && (
            <div className="col-span-full text-center py-12 text-gray-400">
              No agents match your filters
            </div>
          )}
        </div>
      )}

      {/* Create Agent Modal */}
      {showCreateModal && (
        <CreateAgentModal
          onClose={() => setShowCreateModal(false)}
          onCreate={handleCreateAgent}
        />
      )}
    </div>
  );
}

function AgentCard({ agent, onClick, onWake, onPause, onDelete, actionLoading }: {
  agent: Agent;
  onClick: () => void;
  onWake: (e: React.MouseEvent) => void;
  onPause: (e: React.MouseEvent) => void;
  onDelete: (e: React.MouseEvent) => void;
  actionLoading: boolean;
}) {
  const config = STATUS_CONFIG[agent.status] || STATUS_CONFIG.idle;
  const StatusIcon = config.icon;
  const canWake = agent.status === 'idle' || agent.status === 'paused';
  const canPause = agent.status === 'ready' || agent.status === 'executing';

  return (
    <div
      onClick={onClick}
      className="p-4 rounded-xl bg-white/[0.03] border border-white/[0.06] hover:border-white/[0.12] hover:bg-white/[0.05] transition-all cursor-pointer group"
    >
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-3">
          <div
            className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-sm"
            style={{ backgroundColor: config.color + '20', color: config.color }}
          >
            {agent.name.charAt(0)}
          </div>
          <div>
            <h3 className="text-sm font-semibold text-white group-hover:text-primary-400 transition-colors">
              {agent.name}
            </h3>
            <p className="text-xs text-gray-400">{agent.title || agent.role}</p>
          </div>
        </div>
        <ChevronRight size={14} className="text-gray-500 group-hover:text-gray-300 transition-colors" />
      </div>

      <div className="flex items-center justify-between mb-3">
        <span
          className="flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full"
          style={{ color: config.color, backgroundColor: config.color + '15' }}
        >
          <StatusIcon size={10} />
          {config.label}
        </span>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Cpu size={10} />
          <span>{agent.model || agent.adapter_type}</span>
        </div>
      </div>

      {agent.capabilities && agent.capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-3">
          {agent.capabilities.slice(0, 3).map((cap) => (
            <span key={cap} className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.04] text-gray-400">
              {cap}
            </span>
          ))}
          {agent.capabilities.length > 3 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.04] text-gray-500">
              +{agent.capabilities.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Action buttons */}
      <div className="flex items-center gap-2 pt-2 border-t border-white/[0.06]">
        {canWake && (
          <button
            onClick={onWake}
            disabled={actionLoading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] text-green-400 bg-green-500/10 rounded hover:bg-green-500/20 transition-colors disabled:opacity-50"
          >
            <Play size={10} />
            Wake
          </button>
        )}
        {canPause && (
          <button
            onClick={onPause}
            disabled={actionLoading}
            className="flex items-center gap-1 px-2 py-1 text-[10px] text-yellow-400 bg-yellow-500/10 rounded hover:bg-yellow-500/20 transition-colors disabled:opacity-50"
          >
            <Pause size={10} />
            Pause
          </button>
        )}
        <button
          onClick={onDelete}
          disabled={actionLoading}
          className="flex items-center gap-1 px-2 py-1 text-[10px] text-red-400 bg-red-500/10 rounded hover:bg-red-500/20 transition-colors disabled:opacity-50 ml-auto"
        >
          <Trash2 size={10} />
          Delete
        </button>
      </div>
    </div>
  );
}


function CreateAgentModal({ onClose, onCreate }: { onClose: () => void; onCreate: (data: AgentCreateRequest) => Promise<void> }) {
  const [agentMode, setAgentMode] = useState<'llm' | 'cli'>('llm');
  const [formData, setFormData] = useState<AgentCreateRequest>({
    name: '',
    title: '',
    role: 'engineer',
    adapter_type: 'openai',
    model: 'gpt-4o',
    capabilities: [],
    responsibilities: '',
    objectives: '',
    budget_monthly_cents: 30000,
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capInput, setCapInput] = useState('');

  // Fetch CLI backends from API
  const { data: cliBackends } = useApi<Array<{ id: string; name: string; command: string; description: string; installed: boolean; version: string | null; path: string | null }>>(
    () => apiClient.get('/api/v1/adapters/cli-backends'),
    [],
  );

  const CLI_BACKENDS = cliBackends ?? [];

  const handleModeChange = (mode: 'llm' | 'cli') => {
    setAgentMode(mode);
    if (mode === 'cli') {
      setFormData({ ...formData, adapter_type: 'cli', model: 'claude' });
    } else {
      setFormData({ ...formData, adapter_type: 'openai', model: 'gpt-4o' });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name.trim()) { setError('Name is required'); return; }
    setSubmitting(true);
    setError(null);
    try {
      await onCreate(formData);
    } catch (err: any) {
      setError(err?.message || 'Failed to create agent');
    } finally {
      setSubmitting(false);
    }
  };

  const addCapability = () => {
    if (capInput.trim() && !formData.capabilities?.includes(capInput.trim())) {
      setFormData({ ...formData, capabilities: [...(formData.capabilities || []), capInput.trim()] });
      setCapInput('');
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
      <div className="w-full max-w-lg mx-4 bg-[#0B1626] border border-white/10 rounded-xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h2 className="text-lg font-semibold text-white">Hire New Agent</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[70vh] overflow-y-auto">
          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400">
              {error}
            </div>
          )}

          {/* Agent Type Toggle */}
          <div>
            <label className="block text-xs text-gray-400 mb-2">Agent Type</label>
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => handleModeChange('llm')}
                className={`p-3 rounded-lg border text-left transition-all ${
                  agentMode === 'llm'
                    ? 'border-primary-500 bg-primary-500/10'
                    : 'border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.04]'
                }`}
              >
                <p className={`text-sm font-medium ${agentMode === 'llm' ? 'text-primary-400' : 'text-gray-300'}`}>
                  LLM Provider
                </p>
                <p className="text-[10px] text-gray-500 mt-0.5">OpenAI, Anthropic, Ollama APIs</p>
              </button>
              <button
                type="button"
                onClick={() => handleModeChange('cli')}
                className={`p-3 rounded-lg border text-left transition-all ${
                  agentMode === 'cli'
                    ? 'border-green-500 bg-green-500/10'
                    : 'border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.04]'
                }`}
              >
                <p className={`text-sm font-medium ${agentMode === 'cli' ? 'text-green-400' : 'text-gray-300'}`}>
                  IDE / CLI Agent
                </p>
                <p className="text-[10px] text-gray-500 mt-0.5">Claude Code, Kiro, Aider, Codex</p>
              </button>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Name *</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                placeholder="e.g. Atlas"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1">Title</label>
              <input
                type="text"
                value={formData.title}
                onChange={(e) => setFormData({ ...formData, title: e.target.value })}
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                placeholder="e.g. Senior Engineer"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Role</label>
              <select
                value={formData.role}
                onChange={(e) => setFormData({ ...formData, role: e.target.value })}
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
              >
                <option value="engineer">Engineer</option>
                <option value="researcher">Researcher</option>
                <option value="pm">Project Manager</option>
                <option value="qa">QA Engineer</option>
                <option value="devops">DevOps</option>
                <option value="cto">CTO</option>
                <option value="ceo">CEO</option>
              </select>
            </div>

            {/* LLM mode: provider + model */}
            {agentMode === 'llm' && (
              <div>
                <label className="block text-xs text-gray-400 mb-1">Provider</label>
                <select
                  value={formData.adapter_type}
                  onChange={(e) => setFormData({ ...formData, adapter_type: e.target.value })}
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                >
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="ollama">Ollama (Local)</option>
                </select>
              </div>
            )}

            {/* CLI mode: backend selector */}
            {agentMode === 'cli' && (
              <div>
                <label className="block text-xs text-gray-400 mb-1">IDE Backend</label>
                <select
                  value={formData.model}
                  onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                  className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                >
                  {CLI_BACKENDS.map((b) => (
                    <option key={b.id} value={b.id} disabled={!b.installed}>
                      {b.installed ? '●' : '○'} {b.name} {!b.installed ? '(not installed)' : ''}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* LLM model selector (only in LLM mode) */}
          {agentMode === 'llm' && (
            <div>
              <label className="block text-xs text-gray-400 mb-1">Model</label>
              <select
                value={formData.model}
                onChange={(e) => setFormData({ ...formData, model: e.target.value })}
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
              >
                {formData.adapter_type === 'openai' && (
                  <>
                    <option value="gpt-4o">GPT-4o</option>
                    <option value="gpt-4o-mini">GPT-4o Mini</option>
                    <option value="o3">O3</option>
                    <option value="o3-mini">O3 Mini</option>
                  </>
                )}
                {formData.adapter_type === 'anthropic' && (
                  <>
                    <option value="claude-sonnet-4-20250514">Claude Sonnet 4</option>
                    <option value="claude-3-5-sonnet-20241022">Claude 3.5 Sonnet</option>
                    <option value="claude-3-5-haiku-20241022">Claude 3.5 Haiku</option>
                  </>
                )}
                {formData.adapter_type === 'ollama' && (
                  <>
                    <option value="llama3.1">Llama 3.1</option>
                    <option value="codellama">Code Llama</option>
                    <option value="mistral">Mistral</option>
                    <option value="deepseek-coder">DeepSeek Coder</option>
                  </>
                )}
              </select>
            </div>
          )}

          {/* CLI backend info (only in CLI mode) */}
          {agentMode === 'cli' && (
            <div className="space-y-2">
              {CLI_BACKENDS.map((b) => {
                const isSelected = formData.model === b.id;
                return (
                  <div
                    key={b.id}
                    onClick={() => b.installed && setFormData({ ...formData, model: b.id })}
                    className={`p-3 rounded-lg border transition-all ${
                      isSelected
                        ? 'border-green-500 bg-green-500/10'
                        : b.installed
                          ? 'border-white/[0.08] bg-white/[0.02] hover:bg-white/[0.04] cursor-pointer'
                          : 'border-white/[0.05] bg-white/[0.01] opacity-50 cursor-not-allowed'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full ${b.installed ? 'bg-green-500' : 'bg-red-500'}`} />
                        <span className={`text-sm font-medium ${isSelected ? 'text-green-400' : 'text-gray-300'}`}>
                          {b.name}
                        </span>
                      </div>
                      <span className="text-[10px] text-gray-500 font-mono">{b.command}</span>
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-[10px] text-gray-500">
                        {b.installed ? (b.version || 'Installed') : 'Not installed'}
                      </span>
                      {b.installed && b.path && (
                        <span className="text-[10px] text-gray-600 truncate max-w-[180px]">{b.path}</span>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1">Monthly Budget (cents)</label>
              <input
                type="number"
                value={formData.budget_monthly_cents}
                onChange={(e) => setFormData({ ...formData, budget_monthly_cents: parseInt(e.target.value) || 0 })}
                className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
              />
            </div>
            <div />
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Responsibilities</label>
            <textarea
              value={formData.responsibilities}
              onChange={(e) => setFormData({ ...formData, responsibilities: e.target.value })}
              rows={2}
              className="w-full bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500 resize-none"
              placeholder="What this agent is responsible for..."
            />
          </div>

          <div>
            <label className="block text-xs text-gray-400 mb-1">Capabilities</label>
            <div className="flex gap-2">
              <input
                type="text"
                value={capInput}
                onChange={(e) => setCapInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addCapability(); } }}
                className="flex-1 bg-dark-bg border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-primary-500"
                placeholder="Type and press Enter"
              />
              <button type="button" onClick={addCapability} className="px-3 py-2 text-xs bg-primary-500/20 text-primary-400 rounded-lg">
                Add
              </button>
            </div>
            {formData.capabilities && formData.capabilities.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {formData.capabilities.map((cap) => (
                  <span key={cap} className="flex items-center gap-1 px-2 py-0.5 text-[10px] bg-white/[0.05] text-gray-300 rounded">
                    {cap}
                    <button
                      type="button"
                      onClick={() => setFormData({ ...formData, capabilities: formData.capabilities?.filter((c) => c !== cap) })}
                      className="text-gray-500 hover:text-red-400"
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-white/[0.06]">
            <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-gray-400 hover:text-white transition-colors">
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-4 py-2 bg-green-500/20 text-green-400 text-sm font-medium rounded-lg hover:bg-green-500/30 transition-colors disabled:opacity-50"
            >
              {submitting ? 'Creating...' : 'Hire Agent'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
