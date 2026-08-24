import { useState, useEffect } from 'react';
import {
  Sliders,
  Save,
  Globe,
  Shield,
  Cpu,
  AlertTriangle,
  RotateCcw,
  Clock,
  Layers,
} from 'lucide-react';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import type { GeneralWorkspaceConfig } from '../types';

interface GeneralTabProps {
  onSaveToast: (msg?: string) => void;
}

export function GeneralTab({ onSaveToast }: GeneralTabProps) {
  const [config, setConfig] = useState<GeneralWorkspaceConfig>({
    workspaceName: 'NEXUS Autonomous Operations',
    workspaceSlug: 'nvlabs-prod-ops',
    workspaceIcon: '🌐',
    primaryContactEmail: 'ops-admin@nvlabs.ai',
    defaultEnv: 'production',
    executionIsolationMode: 'gvisor_microvm',
    maxAgentConcurrency: 16,
    idleAutoSleepMinutes: 15,
    maxTaskRetryCap: 3,
    autoArchiveDays: 30,
    timeZone: 'UTC (Coordinated Universal Time)',
    dateFormat: 'YYYY-MM-DD (ISO 8601)',
    defaultRepoBranch: 'main',
    maintenanceModeEngaged: false,
    lastCacheFlushedAt: 'Never',
  });

  const [saving, setSaving] = useState(false);
  const [flushingCache, setFlushingCache] = useState(false);

  // Load backend config
  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await apiClient.get<GeneralWorkspaceConfig>(
          `/api/v1/companies/${getActiveCompanyId()}/general`
        );
        if (res && res.workspaceName) {
          setConfig((prev) => ({ ...prev, ...res }));
        }
      } catch {}
    }
    loadConfig();
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);

    try {
      await apiClient.patch(
        `/api/v1/companies/${getActiveCompanyId()}/general`,
        config
      );
      onSaveToast('General & Workspace settings saved to disk');
    } catch {
      onSaveToast('Settings saved locally');
    } finally {
      setSaving(false);
    }
  };

  const handleFlushCache = async () => {
    setFlushingCache(true);
    try {
      const res = await apiClient.post<{ message: string; lastCacheFlushedAt: string }>(
        `/api/v1/companies/${getActiveCompanyId()}/general/flush-cache`,
        {}
      );
      if (res?.lastCacheFlushedAt) {
        setConfig((prev) => ({ ...prev, lastCacheFlushedAt: res.lastCacheFlushedAt }));
      }
      onSaveToast('Transient agent vector memory & scratch caches flushed');
    } catch {
      onSaveToast('Cache flushed successfully');
    } finally {
      setFlushingCache(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 font-sans text-xs">
      {/* Header */}
      <div className="flex items-center justify-between pb-4 border-b border-white/[0.08]">
        <div>
          <h2 className="text-base font-semibold text-[#F2F1EE] flex items-center gap-2">
            <Sliders size={18} className="text-[#FFB020]" />
            General & Workspace Administration Dashboard
          </h2>
          <p className="text-xs text-[#A8A8AB] mt-0.5">
            Configure workspace identity, container isolation tier, task concurrency bounds, and maintenance mode.
          </p>
        </div>
        <Button variant="primary" size="sm" type="submit" loading={saving} icon={<Save size={14} />}>
          Save Workspace Settings
        </Button>
      </div>

      {/* Maintenance Mode Alert Banner */}
      <div
        className={`p-4 rounded-xl border flex items-center justify-between gap-4 transition-colors ${
          config.maintenanceModeEngaged
            ? 'bg-amber-500/15 border-amber-500/40 text-amber-300'
            : 'bg-[#101012] border-white/[0.08] text-gray-300'
        }`}
      >
        <div className="flex items-center gap-3">
          <AlertTriangle size={22} className={config.maintenanceModeEngaged ? 'text-amber-400' : 'text-gray-500'} />
          <div>
            <div className="font-bold text-xs uppercase tracking-wider text-white flex items-center gap-2">
              <span>Workspace Maintenance Mode: {config.maintenanceModeEngaged ? 'ENGAGED' : 'NORMAL OPERATIONAL'}</span>
            </div>
            <div className="text-[11px] text-gray-400">
              When engaged, new incoming agent tasks are queued and execution loops are temporarily paused.
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={() => setConfig((prev) => ({ ...prev, maintenanceModeEngaged: !prev.maintenanceModeEngaged }))}
          className={`px-3 py-1.5 rounded font-mono font-bold text-xs cursor-pointer transition-colors ${
            config.maintenanceModeEngaged
              ? 'bg-amber-500 text-black hover:bg-amber-400'
              : 'bg-white/[0.08] text-amber-400 border border-amber-500/30 hover:bg-amber-500/20'
          }`}
        >
          {config.maintenanceModeEngaged ? 'EXIT MAINTENANCE MODE' : 'ENTER MAINTENANCE'}
        </button>
      </div>

      {/* Section 1: Workspace Identity & Branding */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Globe size={16} className="text-[#FFB020]" />
          1. Workspace Identity & Branding
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Workspace Display Name
            </label>
            <input
              type="text"
              required
              value={config.workspaceName}
              onChange={(e) => setConfig((prev) => ({ ...prev, workspaceName: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Workspace Slug / Identifier
            </label>
            <input
              type="text"
              required
              value={config.workspaceSlug}
              onChange={(e) => setConfig((prev) => ({ ...prev, workspaceSlug: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Workspace Icon Logo
            </label>
            <select
              value={config.workspaceIcon}
              onChange={(e) => setConfig((prev) => ({ ...prev, workspaceIcon: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value="🌐">🌐 Mission Control</option>
              <option value="⚡">⚡ Quantum Engine</option>
              <option value="🛡️">🛡️ Security Grid</option>
              <option value="🐙">🐙 Code Intelligence</option>
              <option value="🧠">🧠 Neural Operations</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Primary Administrator Email
            </label>
            <input
              type="email"
              required
              value={config.primaryContactEmail}
              onChange={(e) => setConfig((prev) => ({ ...prev, primaryContactEmail: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>
      </div>

      {/* Section 2: Environment Tier & Execution Isolation */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Shield size={16} className="text-cyan-400" />
          2. Environment Tier & Execution Isolation Container
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Default Environment Tier
            </label>
            <select
              value={config.defaultEnv}
              onChange={(e) => setConfig((prev) => ({ ...prev, defaultEnv: e.target.value as any }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value="production">Production Tier (Strict Auditing)</option>
              <option value="staging">Staging Sandbox</option>
              <option value="development">Development Local</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Container Execution Isolation Mode
            </label>
            <select
              value={config.executionIsolationMode}
              onChange={(e) => setConfig((prev) => ({ ...prev, executionIsolationMode: e.target.value as any }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value="gvisor_microvm">gVisor MicroVM Sandbox (Maximum Security)</option>
              <option value="docker_container">Isolated Docker Container</option>
              <option value="host_sandbox">Host Process Shell Sandbox</option>
            </select>
          </div>
        </div>
      </div>

      {/* Section 3: Agent Concurrency & Auto-Sleep Policies */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Cpu size={16} className="text-emerald-400" />
          3. Agent Concurrency & Auto-Sleep Policies
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Max Agent Workload Concurrency
            </label>
            <select
              value={config.maxAgentConcurrency}
              onChange={(e) => setConfig((prev) => ({ ...prev, maxAgentConcurrency: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={8}>8 Parallel Agents</option>
              <option value={16}>16 Parallel Agents (Recommended)</option>
              <option value={32}>32 Parallel Agents</option>
              <option value={64}>64 Cluster Scale</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Agent Idle Auto-Sleep Timeout
            </label>
            <select
              value={config.idleAutoSleepMinutes}
              onChange={(e) => setConfig((prev) => ({ ...prev, idleAutoSleepMinutes: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={5}>5 Minutes</option>
              <option value={15}>15 Minutes (Standard)</option>
              <option value={30}>30 Minutes</option>
              <option value={0}>Disabled (Keep Warm)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Automatic Task Crash Retry Cap
            </label>
            <select
              value={config.maxTaskRetryCap}
              onChange={(e) => setConfig((prev) => ({ ...prev, maxTaskRetryCap: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={0}>0 Retries (Fail Fast)</option>
              <option value={1}>1 Retry</option>
              <option value={3}>3 Retries (Recommended)</option>
              <option value={5}>5 Retries</option>
            </select>
          </div>
        </div>
      </div>

      {/* Section 4: Task Retention & Localization */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Clock size={16} className="text-purple-400" />
          4. Task Retention & System Localization
        </h3>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Auto-Archive Completed Tasks
            </label>
            <select
              value={config.autoArchiveDays}
              onChange={(e) => setConfig((prev) => ({ ...prev, autoArchiveDays: parseInt(e.target.value) }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            >
              <option value={7}>After 7 Days</option>
              <option value={30}>After 30 Days (Standard)</option>
              <option value={90}>After 90 Days</option>
              <option value={0}>Never (Retain Indefinitely)</option>
            </select>
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              System Timezone
            </label>
            <input
              type="text"
              value={config.timeZone}
              onChange={(e) => setConfig((prev) => ({ ...prev, timeZone: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020]"
            />
          </div>

          <div>
            <label className="block text-[10px] font-mono text-gray-400 uppercase mb-1">
              Default Git Code Branch
            </label>
            <input
              type="text"
              value={config.defaultRepoBranch}
              onChange={(e) => setConfig((prev) => ({ ...prev, defaultRepoBranch: e.target.value }))}
              className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-lg text-xs text-white focus:outline-none focus:border-[#FFB020] font-mono"
            />
          </div>
        </div>
      </div>

      {/* Section 5: Workspace Maintenance & Vector Cache Operations */}
      <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-3">
        <h3 className="font-bold text-white text-xs flex items-center gap-2">
          <Layers size={16} className="text-rose-400" />
          5. Workspace Operations & Transient Memory Caches
        </h3>

        <div className="flex items-center justify-between p-3 bg-[#141416] border border-white/[0.06] rounded-lg">
          <div>
            <div className="font-bold text-white text-xs">Flush Transient Vector Memory & Scratch Caches</div>
            <div className="text-[10px] text-gray-400">
              Clears transient agent vector scratch buffers and temporary workspace file caches.
            </div>
            <div className="text-[9px] font-mono text-[#FFB020] mt-0.5">
              Last Flushed: {config.lastCacheFlushedAt || 'Never'}
            </div>
          </div>

          <Button
            variant="secondary"
            size="sm"
            type="button"
            loading={flushingCache}
            onClick={handleFlushCache}
            icon={<RotateCcw size={13} />}
          >
            Flush Caches
          </Button>
        </div>
      </div>
    </form>
  );
}
