/**
 * CLI backend picker for hiring. The server catalog (GET /api/v1/agent-providers)
 * is authoritative; this component only groups, filters and probes it.
 */

import { probeProvider, type AgentProvider, type ProviderProbe } from '@/api/agents';
import { useState } from 'react';

export type ProviderGroup = 'ready' | 'needs_config' | 'install' | 'catalog_only';

export const GROUP_LABELS: Record<ProviderGroup, string> = {
  ready: 'Installed and ready',
  needs_config: 'Installed but needs configuration',
  install: 'Available to install',
  catalog_only: 'Experimental / catalog only',
};
const GROUP_ORDER: ProviderGroup[] = ['ready', 'needs_config', 'install', 'catalog_only'];

export function providerGroup(p: AgentProvider): ProviderGroup {
  if (!p.execution_supported) return 'catalog_only';
  if (!p.installed) return 'install';
  if (p.configured === false || p.version === null) return 'needs_config';
  return 'ready';
}

/** Catalog-only backends are never selectable; missing ones only with the explicit override. */
export function isSelectable(p: AgentProvider, allowUnavailable: boolean): boolean {
  return p.execution_supported && (p.installed || allowUnavailable);
}

interface CliBackendPickerProps {
  providers: AgentProvider[];
  /** True when the provider API failed and `providers` is the offline fallback. */
  metadataUnavailable: boolean;
  value: string;
  onChange: (backendId: string) => void;
  allowUnavailable: boolean;
  onAllowUnavailableChange: (allow: boolean) => void;
}

const yesNo = (v: boolean | null) => (v === null ? 'unknown' : v ? 'yes' : 'no');

export function CliBackendPicker({
  providers,
  metadataUnavailable,
  value,
  onChange,
  allowUnavailable,
  onAllowUnavailableChange,
}: CliBackendPickerProps) {
  const [search, setSearch] = useState('');
  const [showUnavailable, setShowUnavailable] = useState(false);
  const [probe, setProbe] = useState<ProviderProbe | null>(null);
  const [probeError, setProbeError] = useState<string | null>(null);
  const [probing, setProbing] = useState(false);

  const q = search.trim().toLowerCase();
  const matches = providers.filter(
    (p) => !q || p.id.toLowerCase().includes(q) || p.label.toLowerCase().includes(q),
  );
  const hiddenCount = matches.filter((p) => !p.installed || !p.execution_supported).length;
  const selected = providers.find((p) => p.id === value);

  const select = (id: string) => {
    setProbe(null);
    setProbeError(null);
    onChange(id);
  };

  const runProbe = async () => {
    if (!value) return;
    setProbing(true);
    setProbe(null);
    setProbeError(null);
    try {
      setProbe(await probeProvider(value));
    } catch (err: any) {
      setProbeError(err?.message || 'Probe failed');
    } finally {
      setProbing(false);
    }
  };

  return (
    <div className="space-y-2">
      {metadataUnavailable && (
        <div role="alert" className="p-2 bg-amber-500/10 border border-amber-500/20 rounded-[6px] text-[10px] font-mono text-amber-300">
          Provider metadata unavailable — showing a minimal offline list with unknown status. The server validates the backend on hire.
        </div>
      )}

      <input
        type="search"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search CLI backends..."
        aria-label="Search CLI backends"
        className="w-full px-3 py-1.5 bg-[#141416] border border-white/[0.12] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020]"
      />

      <div className="max-h-56 overflow-y-auto space-y-2 pr-1">
        {GROUP_ORDER.map((group) => {
          if (!showUnavailable && (group === 'install' || group === 'catalog_only')) return null;
          const items = matches.filter((p) => providerGroup(p) === group);
          if (items.length === 0) return null;
          return (
            <div key={group} role="group" aria-label={GROUP_LABELS[group]}>
              <div className="text-[9px] font-mono uppercase text-[#6B6B6E] mb-1">{GROUP_LABELS[group]}</div>
              {items.map((p) => {
                const enabled = isSelectable(p, allowUnavailable);
                return (
                  <button
                    key={p.id}
                    type="button"
                    disabled={!enabled}
                    aria-pressed={p.id === value}
                    onClick={() => select(p.id)}
                    className={`w-full px-2.5 py-1.5 text-left text-xs flex items-center gap-2 rounded-[4px] transition-colors ${
                      p.id === value
                        ? 'bg-[#FFB020]/10 text-[#FFB020]'
                        : enabled
                          ? 'text-[#F2F1EE] hover:bg-white/[0.06] cursor-pointer'
                          : 'text-[#6B6B6E] cursor-not-allowed'
                    }`}
                  >
                    <span className={`w-2 h-2 rounded-full shrink-0 ${group === 'ready' ? 'bg-emerald-400' : group === 'needs_config' ? 'bg-amber-400' : 'bg-gray-600'}`} />
                    <span className="flex-1 truncate">{p.label}</span>
                    <span className="text-[9px] font-mono text-[#6B6B6E]">{p.id}</span>
                    {p.version && <span className="text-[9px] font-mono text-[#6B6B6E] truncate max-w-[6rem]">{p.version}</span>}
                    <span className="text-[9px] font-mono text-[#6B6B6E]">{p.stability}</span>
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 text-[10px] font-mono text-[#9C9C9F]">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={showUnavailable} onChange={(e) => setShowUnavailable(e.target.checked)} />
          Show unavailable ({hiddenCount})
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" checked={allowUnavailable} onChange={(e) => onAllowUnavailableChange(e.target.checked)} />
          Allow unavailable backend (hire as configuration required)
        </label>
      </div>

      {selected && (
        <div className="p-2.5 bg-[#101012] border border-white/[0.08] rounded-[6px] text-[10px] font-mono text-[#A8A8AB] space-y-1">
          <div className="text-xs text-[#F2F1EE]">
            {selected.label} <span className="text-[#6B6B6E]">({selected.id})</span>
          </div>
          <div>
            installed: {yesNo(selected.installed)} · version: {selected.version ?? '—'} · executable: {selected.execution_supported ? 'yes' : 'catalog only'} · configured: {yesNo(selected.configured)} · {selected.stability}
          </div>
          <div>
            model: {yesNo(selected.supports_model)} · resume: {yesNo(selected.supports_resume)} · interactive: {yesNo(selected.supports_interactive)} · worktree: {yesNo(selected.supports_worktree)}
            {selected.instruction_path && <> · instructions: {selected.instruction_path}</>}
          </div>
          {selected.notes && <div className="text-[#6B6B6E]">{selected.notes}</div>}
          {!selected.installed && (selected.install_command || selected.docs_url) && (
            <div>
              {selected.install_command && <>install: <code className="text-[#F2F1EE]">{selected.install_command}</code> </>}
              {selected.docs_url && (
                <a href={selected.docs_url} target="_blank" rel="noreferrer" className="text-[#FFB020] hover:underline">
                  docs
                </a>
              )}
            </div>
          )}
          <div className="flex items-center gap-2 pt-1">
            <button
              type="button"
              onClick={runProbe}
              disabled={probing}
              className="px-2 py-0.5 border border-white/[0.12] hover:border-[#FFB020]/50 rounded text-[10px] text-[#F2F1EE] cursor-pointer disabled:opacity-50"
            >
              {probing ? 'Testing...' : 'Test CLI'}
            </button>
            {probe?.ok && (
              <span className="text-emerald-400">
                OK — {probe.version}
                {probe.resolved_command && <> at {probe.resolved_command}</>}
              </span>
            )}
            {probe && !probe.ok && <span className="text-red-400">Failed — {probe.error}</span>}
            {probeError && <span className="text-red-400">Failed — {probeError}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
