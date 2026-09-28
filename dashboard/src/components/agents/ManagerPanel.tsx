/**
 * ManagerPanel — a manager agent's direct reports and their work.
 *
 * Reads the deterministic roll-up from GET /api/v1/agents/{id}/rollup
 * (`nexus/services/manager_service.py`). Nothing here is computed by an LLM.
 * Also the manager's hiring requests (`nexus/services/hiring_service.py`),
 * decided through the existing approval endpoints.
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

export interface HiringRequest {
  id: string;
  status: 'approval_required' | 'approved' | 'hired' | 'rejected';
  approval_status: string;
  request: {
    role: string;
    title: string;
    backend: string;
    model: string | null;
    estimated_monthly_cents: number;
    estimated_one_time_cents: number;
  };
  policy_decision: string | null;
  policy_rule: string | null;
  policy_reasons: { code: string; message: string }[];
  decided_by: string | null;
  rejection_reason: string | null;
  employee: { id: string; name: string } | null;
}

const HIRE_BADGE: Record<HiringRequest['status'], BadgeVariant> = {
  approval_required: 'pending',
  approved: 'warning',
  hired: 'completed',
  rejected: 'failed',
};

const dollars = (cents: number) => `$${(cents / 100).toFixed(2)}`;

function HiringRequests({ agentId }: { agentId: string }) {
  const [rows, setRows] = useState<HiringRequest[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [reasons, setReasons] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      setRows(await apiClient.get<HiringRequest[]>(`/api/v1/agents/${agentId}/hiring-requests`));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load hiring requests');
    }
  }, [agentId]);

  useEffect(() => {
    void load();
  }, [load]);

  const decide = async (id: string, action: 'approve' | 'reject') => {
    setBusy(id);
    setError(null);
    try {
      await apiClient.post(`/api/v1/approvals/${id}/${action}`, { decision_note: reasons[id]?.trim() || null });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not record the decision');
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card header={<span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">Hiring</span>}>
      {error && <p role="alert" className="text-xs text-[#EF4444]">{error}</p>}
      {rows?.length === 0 && <p className="text-xs text-[#6B6B6E]">No hiring requests.</p>}
      <ul className="space-y-2">
        {rows?.map((r) => (
          <li key={r.id} className="rounded-md border border-[#222] p-3 text-xs" data-testid="hire-row">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-[#F2F1EE]">
                {r.request.title} <span className="text-[#6B6B6E]">({r.request.role})</span>
              </span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-[#6B6B6E]">
                  {r.request.backend}
                  {r.request.model && ` · ${r.request.model}`}
                </span>
                <Badge variant={HIRE_BADGE[r.status] ?? 'neutral'} dot>{r.status}</Badge>
              </div>
            </div>
            <p className="mt-1 text-[#A1A1A6]">
              {dollars(r.request.estimated_monthly_cents)}/month · {dollars(r.request.estimated_one_time_cents)} one-time
              {' · '}policy: {r.policy_decision ?? 'n/a'}
              {r.policy_rule && <span className="font-mono text-[#6B6B6E]"> ({r.policy_rule})</span>}
            </p>
            {r.policy_reasons.length > 0 && (
              <p className="mt-1 text-[#6B6B6E]">{r.policy_reasons.map((x) => x.message).join('; ')}</p>
            )}
            {r.decided_by && <p className="mt-1 text-[#6B6B6E]">Decided by {r.decided_by}</p>}
            {r.rejection_reason && <p className="mt-1 text-[#EF4444]">Rejected: {r.rejection_reason}</p>}
            {r.employee && <p className="mt-1 text-[#A1A1A6]">Employee: {r.employee.name}</p>}
            {r.status === 'approval_required' && (
              <div className="mt-2 flex items-center gap-2">
                <input
                  aria-label={`Decision note for ${r.request.title}`}
                  placeholder="Note (required to reject)"
                  className="flex-1 rounded border border-[#222] bg-transparent px-2 py-1 text-[#F2F1EE]"
                  value={reasons[r.id] ?? ''}
                  onChange={(e) => setReasons((prev) => ({ ...prev, [r.id]: e.target.value }))}
                />
                <Button size="sm" onClick={() => void decide(r.id, 'approve')} disabled={busy === r.id}>
                  Approve
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => void decide(r.id, 'reject')}
                  disabled={busy === r.id || !reasons[r.id]?.trim()}
                >
                  Reject
                </Button>
              </div>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
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
    <div className="space-y-4">
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
    <HiringRequests agentId={agentId} />
    </div>
  );
}
