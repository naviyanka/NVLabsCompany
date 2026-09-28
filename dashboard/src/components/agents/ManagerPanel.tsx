/**
 * ManagerPanel — a manager agent's direct reports and their work.
 *
 * Reads the deterministic roll-up from GET /api/v1/agents/{id}/rollup
 * (`nexus/services/manager_service.py`). Nothing here is computed by an LLM.
 */

import { apiClient } from '@/api/client';
import { Badge, type BadgeVariant } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';

interface AttemptRef {
  task_title: string | null;
  status: string;
  summary: string | null;
  error_code: string | null;
  error: string | null;
}

interface ReportStatus {
  employee: { id: string; name: string; title: string | null };
  state: string;
  active: AttemptRef | null;
  progress: { report: { progress_percent?: number; current_step?: string; blockers?: string[] } | null } | null;
  last_success: AttemptRef | null;
  latest_failure: AttemptRef | null;
  backend: string | null;
}

export interface Rollup {
  direct_reports: ReportStatus[];
  summary: string;
  generated_at: string;
}

const STATE_BADGE: Record<string, BadgeVariant> = {
  working: 'working',
  queued: 'pending',
  idle: 'idle',
  paused: 'paused',
  stale: 'warning',
  failed: 'failed',
  blocked: 'danger',
  expired: 'error',
};

function blocker(s: ReportStatus): string | null {
  const reported = s.progress?.report?.blockers?.[0];
  if (reported) return reported;
  if (s.state === 'failed' || s.state === 'blocked' || s.state === 'expired') {
    const f = s.latest_failure;
    return f ? `${f.task_title ?? 'task'}: ${f.error ?? f.error_code ?? f.status}` : null;
  }
  return null;
}

export function ManagerPanel({ agentId }: { agentId: string }) {
  const [rollup, setRollup] = useState<Rollup | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRollup(await apiClient.get<Rollup>(`/api/v1/agents/${agentId}/rollup`));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the team roll-up');
    } finally {
      setLoading(false);
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card
      header={
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Direct Reports</span>
          <Button size="sm" variant="secondary" onClick={() => void load()} disabled={loading} aria-label="Refresh">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Refresh
          </Button>
        </div>
      }
    >
      {error && <p role="alert" className="text-xs text-[#EF4444]">{error}</p>}
      {rollup && (
        <div className="space-y-3">
          <p className="text-xs text-[#A1A1A6]">{rollup.summary}</p>
          {rollup.direct_reports.length === 0 && (
            <p className="text-xs text-[#6B6B6E]">No direct reports. Set a reporting line to delegate work.</p>
          )}
          <ul className="space-y-2">
            {rollup.direct_reports.map((s) => {
              const report = s.progress?.report;
              const stuck = blocker(s);
              return (
                <li key={s.employee.id} className="rounded-md border border-[#222] p-3 text-xs" data-testid="report-row">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-medium text-[#F2F1EE]">{s.employee.name}</span>
                    <div className="flex items-center gap-2">
                      {s.backend && <span className="font-mono text-[#6B6B6E]">{s.backend}</span>}
                      <Badge variant={STATE_BADGE[s.state] ?? 'neutral'} dot>{s.state}</Badge>
                    </div>
                  </div>
                  {s.active && (
                    <p className="mt-1 text-[#A1A1A6]">
                      {s.active.task_title}
                      {report?.progress_percent !== undefined && ` · ${report.progress_percent}%`}
                      {report?.current_step && ` · ${report.current_step}`}
                    </p>
                  )}
                  {stuck && <p className="mt-1 text-[#EF4444]">Blocker: {stuck}</p>}
                  {s.last_success && (
                    <p className="mt-1 text-[#6B6B6E]">
                      Latest result: {s.last_success.task_title}
                      {s.last_success.summary && ` — ${s.last_success.summary}`}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
          <p className="text-[10px] font-mono text-[#6B6B6E]">As of {new Date(rollup.generated_at).toLocaleString()}</p>
        </div>
      )}
    </Card>
  );
}
