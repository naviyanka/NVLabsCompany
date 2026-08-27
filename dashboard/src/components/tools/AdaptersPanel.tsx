/**
 * AdaptersPanel — read-only view of the registered execution adapters and CLI
 * backends. Surfaces what the platform can actually call (previously only
 * visible in the backend AdapterRegistry).
 *
 * Wraps:
 *   GET /api/v1/adapters                       -> [{ adapter_type, description }]
 *   GET /api/v1/adapters/cli-backends          -> [{ id, name, command, installed, version, ... }]
 */

import { apiClient } from '@/api/client';
import { Boxes, CheckCircle2, Cpu, Terminal, XCircle } from 'lucide-react';
import { useEffect, useState } from 'react';

interface AdapterType {
  adapter_type: string;
  description: string;
}

interface CliBackend {
  id: string;
  name: string;
  command: string;
  description?: string;
  guard_type?: string;
  installed: boolean;
  path?: string | null;
  version?: string | null;
}

export function AdaptersPanel() {
  const [adapters, setAdapters] = useState<AdapterType[]>([]);
  const [cli, setCli] = useState<CliBackend[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    Promise.allSettled([
      apiClient.get<AdapterType[]>('/api/v1/adapters'),
      apiClient.get<CliBackend[]>('/api/v1/adapters/cli-backends'),
    ])
      .then(([a, c]) => {
        if (cancelled) return;
        if (a.status === 'fulfilled' && Array.isArray(a.value)) setAdapters(a.value);
        if (c.status === 'fulfilled' && Array.isArray(c.value)) setCli(c.value);
      })
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
  }, []);

  const installedCli = cli.filter((b) => b.installed).length;

  if (loading) {
    return <div className="p-8 text-center text-xs font-mono text-[#6B6B6E]">Loading adapters…</div>;
  }

  return (
    <div className="space-y-6 font-sans">
      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>Execution Adapters</span>
            <Boxes size={14} className="text-[#FFB020]" />
          </div>
          <div className="text-2xl font-bold font-mono text-[#FFB020] mt-1">{adapters.length}</div>
          <p className="text-[10px] text-gray-500 mt-1">Registered adapter types</p>
        </div>
        <div className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
          <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
            <span>CLI Backends Installed</span>
            <Terminal size={14} className="text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400 mt-1">{installedCli}/{cli.length}</div>
          <p className="text-[10px] text-gray-500 mt-1">Detected on PATH</p>
        </div>
      </div>

      {/* Execution adapters */}
      <div>
        <div className="text-xs font-mono text-[#6B6B6E] uppercase mb-2 flex items-center gap-2">
          <Cpu size={13} /> Execution Adapters
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {adapters.map((a) => (
            <div key={a.adapter_type} className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px]">
              <div className="text-xs font-medium text-[#F2F1EE] font-mono">{a.adapter_type}</div>
              <div className="text-[10px] text-[#6B6B6E] mt-0.5">{a.description || 'No description.'}</div>
            </div>
          ))}
          {adapters.length === 0 && (
            <div className="text-[11px] font-mono text-[#6B6B6E] p-3">No adapters registered.</div>
          )}
        </div>
      </div>

      {/* CLI backends */}
      <div>
        <div className="text-xs font-mono text-[#6B6B6E] uppercase mb-2 flex items-center gap-2">
          <Terminal size={13} /> CLI Backends
        </div>
        <div className="space-y-2">
          {cli.map((b) => (
            <div
              key={b.id}
              className="p-3 bg-[#141416] border border-white/[0.08] rounded-[8px] flex items-center justify-between gap-3"
            >
              <div className="min-w-0">
                <div className="text-xs font-medium text-[#F2F1EE] flex items-center gap-2">
                  {b.name}
                  <span className="text-[10px] font-mono text-[#6B6B6E]">{b.command}</span>
                </div>
                {b.description && <div className="text-[10px] text-[#6B6B6E] mt-0.5 truncate">{b.description}</div>}
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {b.version && <span className="text-[10px] font-mono text-[#6B6B6E]">{b.version}</span>}
                {b.installed ? (
                  <span className="flex items-center gap-1 text-[10px] font-mono text-emerald-400">
                    <CheckCircle2 size={12} /> installed
                  </span>
                ) : (
                  <span className="flex items-center gap-1 text-[10px] font-mono text-[#6B6B6E]">
                    <XCircle size={12} /> not found
                  </span>
                )}
              </div>
            </div>
          ))}
          {cli.length === 0 && (
            <div className="text-[11px] font-mono text-[#6B6B6E] p-3">No CLI backends detected.</div>
          )}
        </div>
      </div>
    </div>
  );
}
