/**
 * RuntimeControlPanel — start / stop / restart the backend from the dashboard.
 *
 * Talks to the supervisor daemon (via the dashboard's /api/supervisor proxy →
 * localhost:8001), NOT the backend, so these controls work even when the
 * backend is down. The supervisor owns the backend's uvicorn process.
 *
 * If the supervisor itself is not running, the panel says so and shows the
 * one command needed to start it — that is the single always-on piece.
 */

import { Button } from '@/components/common/Button';
import { Play, Power, RefreshCw, RotateCcw, ServerCog } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

interface SupervisorStatus {
  running: boolean;
  healthy: boolean;
  owned: boolean;
  pid: number | null;
  port: number;
  uptime_seconds: number | null;
}

type Verdict = SupervisorStatus & { supervisorUp: boolean };

const START_CMD = 'python -m nexus.supervisor';

async function supervisorFetch(path: string, method: 'GET' | 'POST'): Promise<Response> {
  return fetch(`/api/supervisor${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
  });
}

function humanizeUptime(s: number | null): string {
  if (s === null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

export function RuntimeControlPanel({ onSaveToast }: { onSaveToast: (msg?: string) => void }) {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [busy, setBusy] = useState<null | 'start' | 'stop' | 'restart'>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await supervisorFetch('/status', 'GET');
      if (res.status === 502) {
        setVerdict({ supervisorUp: false, running: false, healthy: false, owned: false, pid: null, port: 8000, uptime_seconds: null });
        return;
      }
      const s: SupervisorStatus = await res.json();
      setVerdict({ supervisorUp: true, ...s });
    } catch {
      setVerdict({ supervisorUp: false, running: false, healthy: false, owned: false, pid: null, port: 8000, uptime_seconds: null });
    }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const act = async (action: 'start' | 'stop' | 'restart') => {
    setBusy(action);
    try {
      const res = await supervisorFetch(`/${action}`, 'POST');
      const body = await res.json().catch(() => ({}));
      if (res.status === 502) {
        onSaveToast('Supervisor is not running — start it first (see the command below).');
      } else {
        onSaveToast(body.message || `Backend ${action} requested.`);
      }
      await refresh();
    } catch {
      onSaveToast(`Failed to ${action} the backend.`);
    } finally {
      setBusy(null);
    }
  };

  const supervisorUp = verdict?.supervisorUp ?? false;
  const running = verdict?.running ?? false;
  const healthy = verdict?.healthy ?? false;

  const statusColor = !supervisorUp ? '#6B6B6E' : healthy ? '#22C55E' : running ? '#FFB020' : '#EF4444';
  const statusLabel = !supervisorUp
    ? 'Supervisor offline'
    : healthy
      ? 'Backend healthy'
      : running
        ? 'Backend starting…'
        : 'Backend stopped';

  return (
    <div className="p-4 bg-[#101012] border border-white/[0.08] rounded-xl space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ServerCog size={16} className="text-[#FFB020]" />
          <h3 className="font-bold text-white text-xs uppercase tracking-wider">Backend Runtime Control</h3>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-1.5 px-2 py-1 rounded text-[10px] font-mono text-gray-400 hover:text-white border border-white/[0.08] cursor-pointer"
        >
          <RefreshCw size={11} /> Refresh
        </button>
      </div>

      {/* Status line */}
      <div className="flex items-center gap-3 p-3 bg-[#141416] border border-white/[0.06] rounded-lg">
        <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: statusColor }} />
        <div className="flex-1 min-w-0">
          <div className="text-xs font-medium text-white">{statusLabel}</div>
          <div className="text-[10px] font-mono text-[#6B6B6E]">
            port {verdict?.port ?? 8000}
            {verdict?.pid != null && <> · pid {verdict.pid}</>}
            {verdict?.uptime_seconds != null && <> · up {humanizeUptime(verdict.uptime_seconds)}</>}
            {verdict?.running && !verdict?.owned && <> · external (not supervisor-owned)</>}
          </div>
        </div>
      </div>

      {/* Controls */}
      {supervisorUp ? (
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            icon={<Play size={14} className="text-emerald-400" />}
            loading={busy === 'start'}
            disabled={busy !== null || running}
            onClick={() => act('start')}
          >
            Start
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<RotateCcw size={14} className="text-[#FFB020]" />}
            loading={busy === 'restart'}
            disabled={busy !== null}
            onClick={() => act('restart')}
          >
            Restart
          </Button>
          <Button
            variant="secondary"
            size="sm"
            icon={<Power size={14} className="text-rose-400" />}
            loading={busy === 'stop'}
            disabled={busy !== null || !running}
            onClick={() => act('stop')}
          >
            Stop
          </Button>
        </div>
      ) : (
        <div className="text-[11px] text-[#A8A8AB] space-y-2">
          <p>
            The supervisor daemon is not reachable. It is the one always-on process that
            owns the backend — start it once, then these controls work even when the
            backend is down.
          </p>
          <div className="flex items-center gap-2">
            <code className="px-2 py-1 rounded bg-[#0C0C0E] border border-white/[0.1] text-[#FFB020] font-mono text-[10px]">
              {START_CMD}
            </code>
            <button
              onClick={() => { navigator.clipboard.writeText(START_CMD); onSaveToast('Command copied.'); }}
              className="px-2 py-1 rounded text-[10px] font-mono text-gray-400 hover:text-white border border-white/[0.08] cursor-pointer"
            >
              Copy
            </button>
          </div>
          <p className="text-[10px] text-[#6B6B6E]">Run it from the <code>src/</code> directory.</p>
        </div>
      )}

      <p className="text-[10px] text-[#6B6B6E] leading-relaxed">
        Restart force-kills the current backend and starts a fresh one. Stopping the backend
        will end active agent runs; the supervisor keeps running so you can start it again.
      </p>
    </div>
  );
}
