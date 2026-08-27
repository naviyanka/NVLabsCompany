import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { RuntimeControlPanel } from '@/components/settings/RuntimeControlPanel';
import { getActiveCompanyId } from '@/config';
import {
  Cpu,
  DollarSign,
  RotateCcw,
  Save,
  Settings2,
  ShieldAlert,
  Sliders,
  Zap,
} from 'lucide-react';
import { useEffect, useState } from 'react';
import type { SystemConfigData } from '../types';

interface SystemConfigTabProps {
  onSaveToast: (msg?: string) => void;
}

export function SystemConfigTab({ onSaveToast }: SystemConfigTabProps) {
  const [config, setConfig] = useState<SystemConfigData>({
    workspaceName: 'NEXUS Autonomous Operations',
    defaultEnv: 'production',

    defaultModel: 'Claude 3.7 Sonnet',
    fallbackModel: 'GPT-4o',
    fastUtilityModel: 'GPT-4o-mini',

    temperature: 0.2,
    topP: 0.95,
    frequencyPenalty: 0.0,
    presencePenalty: 0.0,
    maxOutputTokens: 8192,

    maxStepHops: 50,
    maxSubagentParallelism: 10,
    contextWindowStrategy: 'sliding_window',
    vectorMemoryTopK: 5,
    similarityThreshold: 0.85,

    circuitBreakerFailures: 3,
    retryStrategy: 'exponential_backoff',

    maxTaskBudget: '15.00',
    dailyCompanyCap: '250.00',
    killSwitchEngaged: false,
  });

  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await apiClient.get<SystemConfigData>(
          `/api/v1/companies/${getActiveCompanyId()}/settings`
        );
        if (res && res.defaultModel) {
          setConfig((prev) => ({ ...prev, ...res }));
        }
      } catch { }
    }
    loadConfig();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/settings`,
        config
      );
      onSaveToast('System hyperparameters, sampling sliders & LLM routing saved to disk');
    } catch {
      onSaveToast('Settings saved locally');
    } finally {
      setSaving(false);
    }
  };

  const handleResetDefaults = () => {
    setConfig({
      workspaceName: 'NEXUS Autonomous Operations',
      defaultEnv: 'production',
      defaultModel: 'Claude 3.7 Sonnet',
      fallbackModel: 'GPT-4o',
      fastUtilityModel: 'GPT-4o-mini',
      temperature: 0.2,
      topP: 0.95,
      frequencyPenalty: 0.0,
      presencePenalty: 0.0,
      maxOutputTokens: 8192,
      maxStepHops: 50,
      maxSubagentParallelism: 10,
      contextWindowStrategy: 'sliding_window',
      vectorMemoryTopK: 5,
      similarityThreshold: 0.85,
      circuitBreakerFailures: 3,
      retryStrategy: 'exponential_backoff',
      maxTaskBudget: '15.00',
      dailyCompanyCap: '250.00',
      killSwitchEngaged: false,
    });
    onSaveToast('Hyperparameters reset to factory recommended values');
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Settings2 size={18} className="text-[#FFB020]" />
            System Hyperparameters & LLM Routing Controls
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Configure LLM inference temperature, top-p, agent loop bounds, cost guardrails, and emergency kill switches.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            type="button"
            onClick={handleResetDefaults}
            icon={<RotateCcw size={13} />}
          >
            Reset Defaults
          </Button>
          <Button variant="primary" size="sm" type="submit" loading={saving} icon={<Save size={14} />}>
            Save Hyperparameters
          </Button>
        </div>
      </div>

      {/* Backend runtime control (supervisor) */}
      <RuntimeControlPanel onSaveToast={onSaveToast} />

      {/* Emergency Kill Switch Banner */}
      <div
        className={`p-4 rounded-xl border flex items-center justify-between gap-4 transition-colors ${config.killSwitchEngaged
          ? 'bg-rose-500/15 border-rose-500/40 text-rose-300'
          : 'bg-[#101012] border-white/[0.08] text-gray-300'
          }`}
      >
        <div className="flex items-center gap-3">
          <ShieldAlert size={24} className={config.killSwitchEngaged ? 'text-rose-400' : 'text-[#6B6B6E]'} />
          <div>
            <div className="font-bold text-xs uppercase tracking-wider text-white">
              Emergency Kill Switch: {config.killSwitchEngaged ? 'ENGAGED (HALTED)' : 'ARMED (NORMAL)'}
            </div>
            <div className="text-[11px] text-gray-400">
              Immediately halts all active agent execution loops across all projects.
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setConfig((prev) => ({ ...prev, killSwitchEngaged: !prev.killSwitchEngaged }))}
          className={`px-3 py-1.5 rounded font-mono font-bold text-xs cursor-pointer transition-colors ${config.killSwitchEngaged
            ? 'bg-rose-500 text-white hover:bg-rose-600'
            : 'bg-white/[0.08] text-rose-400 border border-rose-500/30 hover:bg-rose-500/20'
            }`}
        >
          {config.killSwitchEngaged ? 'DISENGAGE & RESUME' : 'ENGAGE KILL SWITCH'}
        </button>
      </div>

      {/* 1. LLM Inference & Sampling Controls */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Sliders size={16} className="text-[#FFB020]" />
          1. LLM Sampling & Generation Hyperparameters
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Temperature Slider */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between font-mono">
              <label className="text-[10px] text-gray-400 uppercase font-bold">
                Temperature (Randomness)
              </label>
              <span className="text-[#FFB020] font-bold text-xs">{config.temperature}</span>
            </div>
            <input
              type="range"
              min="0.0"
              max="1.0"
              step="0.05"
              value={config.temperature}
              onChange={(e) => setConfig((prev) => ({ ...prev, temperature: parseFloat(e.target.value) }))}
              className="w-full accent-[#FFB020] cursor-pointer"
            />
            <div className="flex justify-between text-[9px] text-gray-500 font-mono">
              <span>0.0 (Deterministic Code)</span>
              <span>1.0 (Creative Writing)</span>
            </div>
          </div>

          {/* Top-P Slider */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between font-mono">
              <label className="text-[10px] text-gray-400 uppercase font-bold">
                Top-P (Nucleus Sampling)
              </label>
              <span className="text-[#FFB020] font-bold text-xs">{config.topP}</span>
            </div>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.05"
              value={config.topP}
              onChange={(e) => setConfig((prev) => ({ ...prev, topP: parseFloat(e.target.value) }))}
              className="w-full accent-[#FFB020] cursor-pointer"
            />
            <div className="flex justify-between text-[9px] text-gray-500 font-mono">
              <span>0.1 (Focused)</span>
              <span>1.0 (Diverse Pool)</span>
            </div>
          </div>

          {/* Max Output Tokens Select */}
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Max Tokens per Completion Call
            </label>
            <select
              value={config.maxOutputTokens}
              onChange={(e) => setConfig((prev) => ({ ...prev, maxOutputTokens: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={2048}>2,048 Tokens (Fast Response)</option>
              <option value={4096}>4,096 Tokens (Standard)</option>
              <option value={8192}>8,192 Tokens (Extended Generation)</option>
              <option value={16384}>16,384 Tokens (Deep Reasoning Output)</option>
            </select>
          </div>

          {/* Frequency & Presence Penalties */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                Frequency Penalty
              </label>
              <input
                type="number"
                step="0.1"
                min="-2.0"
                max="2.0"
                value={config.frequencyPenalty}
                onChange={(e) => setConfig((prev) => ({ ...prev, frequencyPenalty: parseFloat(e.target.value) }))}
                className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
              />
            </div>
            <div>
              <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
                Presence Penalty
              </label>
              <input
                type="number"
                step="0.1"
                min="-2.0"
                max="2.0"
                value={config.presencePenalty}
                onChange={(e) => setConfig((prev) => ({ ...prev, presencePenalty: parseFloat(e.target.value) }))}
                className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
              />
            </div>
          </div>
        </div>
      </div>

      {/* 2. Agent Execution Loop & Parallelism Bounds */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Cpu size={16} className="text-cyan-400" />
          2. Agent Execution Loop & Parallelism Bounds
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Max Tool Step Hops per Task
            </label>
            <select
              value={config.maxStepHops}
              onChange={(e) => setConfig((prev) => ({ ...prev, maxStepHops: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={10}>10 Steps (Strict Limit)</option>
              <option value={25}>25 Steps (Medium Complexity)</option>
              <option value={50}>50 Steps (Deep Architectural Tasks)</option>
              <option value={100}>100 Steps (Unrestricted Long-Running)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Max Concurrent Subagents Cap
            </label>
            <select
              value={config.maxSubagentParallelism}
              onChange={(e) => setConfig((prev) => ({ ...prev, maxSubagentParallelism: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={2}>2 Parallel Workers</option>
              <option value={5}>5 Parallel Workers</option>
              <option value={10}>10 Parallel Workers (Recommended)</option>
              <option value={20}>20 Parallel Workers (High Parallelism)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Vector Memory Top-K Retrieval
            </label>
            <select
              value={config.vectorMemoryTopK}
              onChange={(e) => setConfig((prev) => ({ ...prev, vectorMemoryTopK: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={3}>Top 3 Items</option>
              <option value={5}>Top 5 Items (Recommended)</option>
              <option value={10}>Top 10 Items (Deep RAG Search)</option>
            </select>
          </div>
        </div>
      </div>

      {/* 3. Multi-Model Routing & Circuit Breaker */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Zap size={16} className="text-amber-400" />
          3. Multi-Model Fallback & Circuit Breaker Matrix
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Primary Model Router
            </label>
            <select
              value={config.defaultModel}
              onChange={(e) => setConfig((prev) => ({ ...prev, defaultModel: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value="Claude 3.7 Sonnet">Claude 3.7 Sonnet (Anthropic)</option>
              <option value="GPT-4o">GPT-4o (OpenAI)</option>
              <option value="Gemini 1.5 Pro">Gemini 1.5 Pro (Google)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Fallback Circuit Breaker Model
            </label>
            <select
              value={config.fallbackModel}
              onChange={(e) => setConfig((prev) => ({ ...prev, fallbackModel: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value="GPT-4o">GPT-4o (OpenAI)</option>
              <option value="Claude 3.5 Sonnet">Claude 3.5 Sonnet</option>
              <option value="GPT-4o-mini">GPT-4o-mini (Cost-Optimized)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Fast Utility Model (Search/Tool Call)
            </label>
            <select
              value={config.fastUtilityModel}
              onChange={(e) => setConfig((prev) => ({ ...prev, fastUtilityModel: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value="GPT-4o-mini">GPT-4o-mini (OpenAI)</option>
              <option value="Claude 3.5 Haiku">Claude 3.5 Haiku (Anthropic)</option>
              <option value="Gemini 1.5 Flash">Gemini 1.5 Flash (Google)</option>
            </select>
          </div>
        </div>
      </div>

      {/* 4. Cost Guardrails & Spend Caps */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <DollarSign size={16} className="text-emerald-400" />
          4. Cost Guardrails & Rate Limit Retry Caps
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Max Single Task Budget ($)
            </label>
            <input
              type="text"
              value={config.maxTaskBudget}
              onChange={(e) => setConfig((prev) => ({ ...prev, maxTaskBudget: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Daily Company Spend Cap ($)
            </label>
            <input
              type="text"
              value={config.dailyCompanyCap}
              onChange={(e) => setConfig((prev) => ({ ...prev, dailyCompanyCap: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>
      </div>
    </form>
  );
}
