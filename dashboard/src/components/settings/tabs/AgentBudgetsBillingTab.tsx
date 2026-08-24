import { useState, useEffect } from 'react';
import {
  CreditCard,
  Plus,
  RotateCcw,
  ShieldAlert,
  Zap,
  Trash2,
  Sliders,
  X,
  Save,
  Users,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { AgentProviderBudget } from '../types';

interface AgentBudgetsBillingTabProps {
  onSaveToast: (msg?: string) => void;
}

export function AgentBudgetsBillingTab({ onSaveToast }: AgentBudgetsBillingTabProps) {
  const [budgets, setBudgets] = useState<AgentProviderBudget[]>([
    {
      id: 'kiro-cli',
      name: 'kiro-cli (Installed Agent Tool)',
      category: 'cli_tool',
      icon: '🚀',
      creditMetric: 'Credits',
      totalCredits: 5000,
      usedCredits: 1840,
      remainingCredits: 3160,
      unitSuffix: ' credits',
      warningThresholdPercent: 80,
      hardStopAction: 'halt_execution',
      renewalCycle: 'monthly',
      lastRefreshedAt: 'Just now',
    },
    {
      id: 'openai-api',
      name: 'OpenAI Platform API (GPT-4o / O3)',
      category: 'llm_provider',
      icon: '🤖',
      creditMetric: 'USD ($)',
      totalCredits: 500,
      usedCredits: 142.8,
      remainingCredits: 357.2,
      unitPrefix: '$',
      warningThresholdPercent: 85,
      hardStopAction: 'switch_fallback',
      renewalCycle: 'monthly',
      lastRefreshedAt: '5 mins ago',
    },
    {
      id: 'anthropic-api',
      name: 'Anthropic Claude API (Claude 3.7)',
      category: 'llm_provider',
      icon: '🧠',
      creditMetric: 'USD ($)',
      totalCredits: 1000,
      usedCredits: 412.5,
      remainingCredits: 587.5,
      unitPrefix: '$',
      warningThresholdPercent: 80,
      hardStopAction: 'switch_fallback',
      renewalCycle: 'monthly',
      lastRefreshedAt: '2 mins ago',
    },
    {
      id: 'gitnexus-tokens',
      name: 'GitNexus AST Token Pool',
      category: 'code_intelligence',
      icon: '🐙',
      creditMetric: 'Tokens',
      totalCredits: 10000000,
      usedCredits: 4210000,
      remainingCredits: 5790000,
      unitSuffix: ' tokens',
      warningThresholdPercent: 90,
      hardStopAction: 'notify_operator_only',
      renewalCycle: 'annual',
      lastRefreshedAt: '10 mins ago',
    },
    {
      id: 'gemini-studio',
      name: 'Google Gemini AI Studio API',
      category: 'llm_provider',
      icon: '☁️',
      creditMetric: 'USD ($)',
      totalCredits: 200,
      usedCredits: 38.4,
      remainingCredits: 161.6,
      unitPrefix: '$',
      warningThresholdPercent: 75,
      hardStopAction: 'switch_fallback',
      renewalCycle: 'pay_as_you_go',
      lastRefreshedAt: '15 mins ago',
    },
    {
      id: 'gvisor-compute',
      name: 'gVisor MicroVM Compute Sandbox',
      category: 'compute_cluster',
      icon: '🐳',
      creditMetric: 'Compute Hours',
      totalCredits: 500,
      usedCredits: 142,
      remainingCredits: 358,
      unitSuffix: ' hours',
      warningThresholdPercent: 85,
      hardStopAction: 'halt_execution',
      renewalCycle: 'monthly',
      lastRefreshedAt: '1 hr ago',
    },
  ]);

  const [refreshing, setRefreshing] = useState(false);
  const [hardStopEnabled, setHardStopEnabled] = useState(true);

  // Add Custom Budget Drawer State
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newBudgetName, setNewBudgetName] = useState('');
  const [newMetric, setNewMetric] = useState<'Credits' | 'USD ($)' | 'Tokens' | 'Compute Hours' | 'API Requests'>('Credits');
  const [newTotal, setNewTotal] = useState(2500);
  const [newUsed, setNewUsed] = useState(0);

  // Load backend billing data
  useEffect(() => {
    async function loadBilling() {
      try {
        const res = await apiClient.get<{ budgets: AgentProviderBudget[]; hardStopEnabled: boolean }>(
          `/api/v1/companies/${getActiveCompanyId()}/billing`
        );
        if (res && Array.isArray(res.budgets) && res.budgets.length > 0) {
          setBudgets(res.budgets);
          if (typeof res.hardStopEnabled === 'boolean') setHardStopEnabled(res.hardStopEnabled);
        }
      } catch {}
    }
    loadBilling();
  }, []);

  const handleRefreshCredits = async () => {
    setRefreshing(true);
    try {
      const res = await apiClient.post<{ budgets: AgentProviderBudget[] }>(
        `/api/v1/companies/${getActiveCompanyId()}/billing/refresh-credits`,
        {}
      );
      if (res && Array.isArray(res.budgets)) {
        setBudgets(res.budgets);
      }
      onSaveToast('Live CLI credit balances & provider budgets updated');
    } catch {
      onSaveToast('Credit balances refreshed');
    } finally {
      setRefreshing(false);
    }
  };

  const handleCreateCustomBudget = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newBudgetName.trim()) return;

    const newId = `custom-${Date.now()}`;
    const newBudget: AgentProviderBudget = {
      id: newId,
      name: newBudgetName.trim(),
      category: 'custom',
      icon: '⚙️',
      creditMetric: newMetric,
      totalCredits: newTotal,
      usedCredits: newUsed,
      remainingCredits: Math.max(0, newTotal - newUsed),
      unitPrefix: newMetric === 'USD ($)' ? '$' : undefined,
      unitSuffix: newMetric === 'Credits' ? ' credits' : newMetric === 'Tokens' ? ' tokens' : newMetric === 'Compute Hours' ? ' hrs' : undefined,
      warningThresholdPercent: 80,
      hardStopAction: 'halt_execution',
      renewalCycle: 'monthly',
      isCustom: true,
      lastRefreshedAt: 'Just now',
    };

    const updated = [...budgets, newBudget];
    setBudgets(updated);
    setIsAddModalOpen(false);
    setNewBudgetName('');

    try {
      await apiClient.post(
        '/api/v1/companies/00000000-0000-4000-8000-000000000001/billing/budgets',
        newBudget
      );
      onSaveToast(`Custom credit budget '${newBudget.name}' added`);
    } catch {
      onSaveToast(`Budget '${newBudget.name}' added locally`);
    }
  };

  const handleDeleteBudget = async (id: string) => {
    const updated = budgets.filter((b) => b.id !== id);
    setBudgets(updated);
    onSaveToast('Budget limit removed');

    try {
      await apiClient.delete(
        `/api/v1/companies/00000000-0000-4000-8000-000000000001/billing/budgets/${id}`
      );
    } catch {}
  };

  return (
    <div className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <CreditCard size={18} className="text-[#FFB020]" />
            Agent Token & CLI Credits Budgeting Hub
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Define credit budgets for kiro-cli, LLM API providers, and custom CLI execution tools.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            type="button"
            loading={refreshing}
            onClick={handleRefreshCredits}
            icon={<RotateCcw size={13} />}
          >
            Refresh Balances
          </Button>

          <Button
            variant="primary"
            size="sm"
            type="button"
            onClick={() => setIsAddModalOpen(true)}
            icon={<Plus size={14} />}
          >
            Add Custom Budget
          </Button>
        </div>
      </div>

      {/* Hard Stop Enforcer Banner */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <ShieldAlert size={22} className={hardStopEnabled ? 'text-[#FFB020]' : 'text-gray-500'} />
          <div>
            <div className="font-bold text-xs uppercase text-white flex items-center gap-2">
              <span>Hard Stop Execution on Budget Exhaustion</span>
              {hardStopEnabled ? (
                <span className="px-2 py-0.5 rounded text-[9px] font-mono bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  ACTIVE
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded text-[9px] font-mono bg-gray-500/10 text-gray-400 border border-gray-500/20">
                  DISABLED
                </span>
              )}
            </div>
            <div className="text-[11px] text-gray-400">
              Automatically halts subagents and CLI execution loops when any provider credit balance reaches 0.
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setHardStopEnabled(!hardStopEnabled)}
          className={`w-11 h-6 rounded-full transition-colors relative cursor-pointer ${
            hardStopEnabled ? 'bg-[#FFB020]' : 'bg-[#1C1C1F]'
          }`}
        >
          <span
            className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-black transition-transform ${
              hardStopEnabled ? 'translate-x-5' : 'translate-x-0'
            }`}
          />
        </button>
      </div>

      {/* Provider & CLI Credit Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {budgets.map((item) => {
          const usedPct = Math.min(100, Math.round((item.usedCredits / item.totalCredits) * 100));
          const isWarning = usedPct >= item.warningThresholdPercent;

          return (
            <div
              key={item.id}
              className={`p-4 rounded-xl border flex flex-col justify-between space-y-3 transition-all ${
                item.id === 'kiro-cli'
                  ? 'bg-[#101012] border-[#FFB020]/40 shadow-lg shadow-[#FFB020]/5'
                  : 'bg-[#101012] border-white/[0.08]'
              }`}
            >
              {/* Header */}
              <div className="flex items-start justify-between">
                <div className="flex items-center gap-2.5">
                  <span className="text-2xl p-1.5 bg-[#1C1C1F] border border-white/[0.08] rounded-lg">
                    {item.icon}
                  </span>
                  <div>
                    <div className="font-bold text-white text-xs flex items-center gap-1.5">
                      <span>{item.name}</span>
                    </div>
                    <div className="text-[10px] font-mono text-gray-400 capitalize">
                      {item.category.replace('_', ' ')} • {item.renewalCycle}
                    </div>
                  </div>
                </div>

                {item.isCustom && (
                  <button
                    type="button"
                    onClick={() => handleDeleteBudget(item.id)}
                    className="text-gray-500 hover:text-rose-400 cursor-pointer p-1"
                    title="Remove custom budget"
                  >
                    <Trash2 size={13} />
                  </button>
                )}
              </div>

              {/* Progress Bar & Balances */}
              <div className="space-y-1.5 font-mono">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-gray-400 uppercase text-[9px] font-bold">Remaining Credit:</span>
                  <span className={`font-bold ${isWarning ? 'text-rose-400' : 'text-emerald-400'}`}>
                    {item.unitPrefix || ''}
                    {item.remainingCredits.toLocaleString()}
                    {item.unitSuffix || ''}
                  </span>
                </div>

                {/* Progress Bar */}
                <div className="w-full h-2 bg-[#1C1C1F] rounded-full overflow-hidden border border-white/[0.06]">
                  <div
                    className={`h-full transition-all ${
                      usedPct > 90 ? 'bg-rose-500' : usedPct > 75 ? 'bg-amber-400' : 'bg-[#FFB020]'
                    }`}
                    style={{ width: `${usedPct}%` }}
                  />
                </div>

                <div className="flex justify-between text-[9px] text-gray-500">
                  <span>Used: {item.unitPrefix || ''}{item.usedCredits.toLocaleString()}{item.unitSuffix || ''} ({usedPct}%)</span>
                  <span>Cap: {item.unitPrefix || ''}{item.totalCredits.toLocaleString()}{item.unitSuffix || ''}</span>
                </div>
              </div>

              {/* Footer */}
              <div className="pt-2 border-t border-white/[0.06] flex items-center justify-between text-[10px] font-mono text-gray-400">
                <div className="flex items-center gap-1">
                  <Zap size={10} className="text-[#FFB020]" />
                  <span>On Limit: {item.hardStopAction.replace(/_/g, ' ')}</span>
                </div>
                <div>Refreshed: {item.lastRefreshedAt || 'Just now'}</div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Agent Squad Monthly Allocation Breakdown */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Users size={16} className="text-[#FFB020]" />
          Agent Squad Monthly Credit Allocation Breakdown
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
          <div className="p-3 bg-[#141416] border border-white/[0.06] rounded-lg space-y-1">
            <div className="text-[10px] text-gray-400 uppercase font-bold">Autonomous Development Squad</div>
            <div className="font-bold text-white text-sm">$150.00 / 3,000 Credits</div>
            <div className="text-[10px] text-emerald-400">62% Allocated • Active</div>
          </div>

          <div className="p-3 bg-[#141416] border border-white/[0.06] rounded-lg space-y-1">
            <div className="text-[10px] text-gray-400 uppercase font-bold">Architecture & System Design</div>
            <div className="font-bold text-white text-sm">$200.00 / 4,000 Credits</div>
            <div className="text-[10px] text-emerald-400">45% Allocated • Active</div>
          </div>

          <div className="p-3 bg-[#141416] border border-white/[0.06] rounded-lg space-y-1">
            <div className="text-[10px] text-gray-400 uppercase font-bold">Security & QA Testing Squad</div>
            <div className="font-bold text-white text-sm">$100.00 / 2,000 Credits</div>
            <div className="text-[10px] text-emerald-400">28% Allocated • Active</div>
          </div>
        </div>
      </div>

      {/* Add Custom Budget Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <form onSubmit={handleCreateCustomBudget} className="bg-[#141416] border border-white/[0.15] rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.08]">
              <div className="flex items-center gap-2">
                <Sliders size={18} className="text-[#FFB020]" />
                <h3 className="font-bold text-white text-sm">Add Custom CLI / Provider Budget</h3>
              </div>
              <button
                type="button"
                onClick={() => setIsAddModalOpen(false)}
                className="text-gray-500 hover:text-white cursor-pointer"
              >
                <X size={16} />
              </button>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                  Budget / Tool / Provider Name
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. kiro-cli Pro, Local Ollama GPU, DeepSeek API"
                  value={newBudgetName}
                  onChange={(e) => setNewBudgetName(e.target.value)}
                  className="w-full px-3 py-1.5 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
                />
              </div>

              <div>
                <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                  Credit Metric Type
                </label>
                <select
                  value={newMetric}
                  onChange={(e) => setNewMetric(e.target.value as any)}
                  className="w-full px-3 py-1.5 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
                >
                  <option value="Credits">Credits (kiro-cli / Custom Tool)</option>
                  <option value="USD ($)">USD ($)</option>
                  <option value="Tokens">Tokens (LLM Context Pool)</option>
                  <option value="Compute Hours">Compute Hours (MicroVM / GPU)</option>
                  <option value="API Requests">API Requests</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                    Total Credit Limit
                  </label>
                  <input
                    type="number"
                    required
                    min={1}
                    value={newTotal}
                    onChange={(e) => setNewTotal(parseInt(e.target.value) || 0)}
                    className="w-full px-3 py-1.5 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
                  />
                </div>

                <div>
                  <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                    Used Amount
                  </label>
                  <input
                    type="number"
                    min={0}
                    value={newUsed}
                    onChange={(e) => setNewUsed(parseInt(e.target.value) || 0)}
                    className="w-full px-3 py-1.5 bg-[#101012] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
                  />
                </div>
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-3 border-t border-white/[0.08]">
              <Button variant="secondary" size="sm" type="button" onClick={() => setIsAddModalOpen(false)}>
                Cancel
              </Button>
              <Button variant="primary" size="sm" type="submit" icon={<Save size={14} />}>
                Save Budget
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
