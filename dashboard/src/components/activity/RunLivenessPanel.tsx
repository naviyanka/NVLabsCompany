/**
 * RunLivenessPanel — read-only view of heartbeat runs and their liveness.
 *
 * Wraps GET /api/v1/companies/{id}/runs/liveness. Surfaces the watchdog /
 * heartbeat state that was previously backend-only: which runs are live, which
 * look stalled (silent past the suspicion window), and which are confirmed dead.
 */

import { apiClient } from '@/api/client';
import { getActiveCompanyId } from '@/config';
import { Activity, AlertTriangle, HeartPulse, RefreshCw, Skull } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

interface RunLiveness {
  id: string;
  agent_id: string;
  agent_name: string;
  liveness_state: string;
  invocation_source: string;
  process_pid: number | null;
  continuation_attempt: number;
  started_at: string | null;
  last_output_at: string | null;
  finished_at: string | null;
  silent_seconds: number | null;
  stalled: boolean;
}

interface LivenessSummary {
  total: number;
  healthy: number;
  stalled: number;
  confirmed_dead: number;
}

function humanizeSeconds(s: number | null): string {
  if (s === null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

function stateStyle(state: string, stalled: boolean): { color: string; label: string } {
  if (state === 'confirmed_dead') return { color: '#EF4444', label: 'confirmed dead' };
  if (stalled || state === 'suspected_stale') return { color: '#FFB020', label: 'stalled' };
  return { color: '#22C55E', label: 'healthy' };
}

export function RunLivenessPanel() {
  const [items, setItems] = useState<RunLiveness[]>([]);
  const [summary, setSummary] = useState<LivenessSummary>({ total: 0, healthy: 0, stalled: 0, confirmed_dead: 0 });
  const [loading, setLoading] = useState(true);
  const [includeFinished, setIncludeFinished] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await apiClient.get<{ items: RunLiveness[]; summary: LivenessSummary }>(
        `/api/v1/companies/${getActiveCompanyId()}/runs/liveness?include_finished=${includeFinished}`,
      );
      setItems(res.items || []);
      setSummary(res.summary || { total: 0, healthy: 0, stalled: 0, confirmed_dead: 0 });
    } catch (err) {
      console.error('Failed to load run liveness', err);
    } finally {
      setLoading(false);
    }
  }, [includeFinished]);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="space-y-4 font-sans">
      {/* Summary */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: 'Active Runs', value: summary.total, icon: Activity, color: '#38BDF8' },
          { label: 'Healthy', value: summary.healthy, icon: HeartPulse, color: '#22C55E' },
          { label: 'Stalled', value: summary.stalled, icon: AlertTriangle, color: '#FFB020' },
          { label: 'Confirmed Dead', value: summary.confirmed_dead, icon: Skull, color: '#EF4444' },
        ].map((s) => (
          <div key={s.label} className="p-3.5 bg-[#101012] border border-white/[0.08] rounded-[10px]">
            <div className="text-[11px] font-mono text-[#6B6B6E] uppercase flex items-center justify-between">
              <span>{s.label}</span>
              <s.icon size={14} style={{ color: s.color }} />
            </div>
            <div className="text-2xl font-bold font-mono mt-1" style={{ color: s.color }}>{s.value}</div>
          </div>
        ))}
      </div>

      <div className="flex items-center justify-between">
        <label className="flex items-center gap-2 text-[11px] font-mono text-[#6B6B6E] cursor-pointer">
          <input
            type="checkbox"
            checked={includeFinished}
            onChange={(e) => setIncludeFinished(e.target.checked)}
            className="accent-[#FFB020]"
          />
          Include finished runs
        </label>
        <button
          onClick={load}
          className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-mono text-gray-400 hover:text-white border border-white/[0.08] cursor-pointer"
        >
          <RefreshCw size={12} /> Refresh
        </button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-xs font-mono text-[#6B6B6E]">Loading run liveness…</div>
      ) : items.length === 0 ? (
        <div className="p-8 text-center bg-[#101012] border border-white/[0.08] rounded-[10px] text-xs font-mono text-[#6B6B6E]">
          No active runs. Agent heartbeat runs appear here while they execute.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((run) => {
            const st = stateStyle(run.liveness_state, run.stalled);
            return (
              <div
                key={run.id}
                className="p-3 bg-[#141416] border rounded-[8px] flex items-center justify-between gap-3"
                style={{ borderColor: run.stalled || run.liveness_state === 'confirmed_dead' ? st.color + '55' : 'rgba(255,255,255,0.08)' }}
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="w-2 h-2 rounded-full shrink-0" style={{ background: st.color }} />
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-[#F2F1EE] truncate">
                      {run.agent_name}
                      <span className="ml-2 text-[10px] font-mono" style={{ color: st.color }}>{st.label}</span>
                    </div>
                    <div className="text-[10px] font-mono text-[#6B6B6E]">
                      {run.invocation_source}
                      {run.process_pid != null && <> · pid {run.process_pid}</>}
                      {run.continuation_attempt > 0 && <> · attempt {run.continuation_attempt}</>}
                    </div>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-[10px] font-mono text-[#6B6B6E]">
                    silent {humanizeSeconds(run.silent_seconds)}
                  </div>
                  {run.finished_at && (
                    <div className="text-[9px] font-mono text-[#6B6B6E]">finished</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
