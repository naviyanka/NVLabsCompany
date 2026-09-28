/**
 * OrganizationSnapshotPanel — the latest precomputed organization snapshot.
 *
 * Reads GET /api/v1/organization/snapshot (`nexus/services/org_snapshot.py`):
 * a stored, deterministic payload, returned even when stale, with its
 * freshness and the last refresh error kept apart. Refresh regenerates it.
 */

import { apiClient } from '@/api/client';
import { Badge, type BadgeVariant } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { RefreshCw } from 'lucide-react';
import { type ReactNode, useCallback, useEffect, useState } from 'react';

type Counts = Record<string, number>;

interface Snapshot {
  company: { name: string };
  hierarchy: { depth: number; managers: { id: string; name: string; direct_reports: number }[] };
  employees: { total: number; by_status: Counts };
  work: { counts: Counts };
  hiring: { counts: Counts };
  approvals: { pending: number; by_type: Counts };
  budget: {
    company_monthly_cents: number;
    company_spent_cents: number;
    hiring_reserved_cents: number;
    hiring_pending_cents: number;
  };
  incidents: { open: number; items: { id: string; title: string; severity: string }[] };
  summary: { text: string; attention: string[] };
}

export interface SnapshotEnvelope {
  snapshot: Snapshot | null;
  version: number | null;
  generated_at: string | null;
  freshness: { status: 'fresh' | 'stale' | 'rebuilding' | 'failed_refresh'; age_seconds: number | null };
  last_refresh_error: { message: string; at: string | null } | null;
}

const FRESHNESS_BADGE: Record<SnapshotEnvelope['freshness']['status'], BadgeVariant> = {
  fresh: 'completed',
  stale: 'warning',
  rebuilding: 'in_progress',
  failed_refresh: 'failed',
};

const dollars = (cents: number) => `$${(cents / 100).toFixed(2)}`;
const list = (counts: Counts) =>
  Object.entries(counts)
    .map(([k, v]) => `${v} ${k}`)
    .join(', ') || 'none';

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md border border-[#222] p-3 text-xs" data-testid={`snapshot-${title}`}>
      <p className="mb-1 font-mono uppercase text-[#6B6B6E]">{title}</p>
      <div className="space-y-1 text-[#A1A1A6]">{children}</div>
    </div>
  );
}

export function OrganizationSnapshotPanel() {
  const [data, setData] = useState<SnapshotEnvelope | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const run = useCallback(async (request: () => Promise<SnapshotEnvelope>) => {
    setBusy(true);
    setError(null);
    try {
      setData(await request());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the organization snapshot');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run(() => apiClient.get<SnapshotEnvelope>('/api/v1/organization/snapshot'));
  }, [run]);

  const s = data?.snapshot;
  return (
    <Card
      header={
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">
            Organization Snapshot{data?.version != null && ` · v${data.version}`}
          </span>
          <div className="flex items-center gap-2">
            {data && (
              <Badge variant={FRESHNESS_BADGE[data.freshness.status] ?? 'neutral'} dot>
                {data.freshness.status}
              </Badge>
            )}
            <Button
              size="sm"
              variant="secondary"
              onClick={() => void run(() => apiClient.post<SnapshotEnvelope>('/api/v1/organization/snapshot/refresh'))}
              disabled={busy}
              aria-label="Refresh snapshot"
            >
              <RefreshCw size={12} className={busy ? 'animate-spin' : ''} /> Refresh
            </Button>
          </div>
        </div>
      }
    >
      {error && <p role="alert" className="text-xs text-[#EF4444]">{error}</p>}
      {data?.last_refresh_error && (
        <p role="alert" className="mb-2 text-xs text-[#EF4444]">
          Last refresh failed: {data.last_refresh_error.message}
        </p>
      )}
      {data && !s && <p className="text-xs text-[#6B6B6E]">No snapshot yet. Refresh to generate one.</p>}
      {s && (
        <div className="space-y-3">
          <p className="text-xs text-[#A1A1A6]">{s.summary.text}</p>
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
            <Section title="hierarchy">
              <p>
                {s.hierarchy.managers.length} manager(s), depth {s.hierarchy.depth}
              </p>
              {s.hierarchy.managers.map((m) => (
                <p key={m.id}>
                  {m.name}: {m.direct_reports} direct report(s)
                </p>
              ))}
            </Section>
            <Section title="workforce">
              <p>
                {s.employees.total} employee(s): {list(s.employees.by_status)}
              </p>
              <p>Work: {list(s.work.counts)}</p>
            </Section>
            <Section title="human actions">
              <p>{s.approvals.pending} pending approval(s)</p>
              {s.approvals.pending > 0 && <p>{list(s.approvals.by_type)}</p>}
            </Section>
            <Section title="budget">
              <p>
                {dollars(s.budget.company_spent_cents)} of {dollars(s.budget.company_monthly_cents)} spent
              </p>
              <p>
                Hiring: {dollars(s.budget.hiring_reserved_cents)} reserved, {dollars(s.budget.hiring_pending_cents)}{' '}
                pending
              </p>
              <p>Requests: {list(s.hiring.counts)}</p>
            </Section>
            <Section title="blockers">
              {s.summary.attention.length === 0 && s.incidents.open === 0 && <p>None.</p>}
              {s.summary.attention.map((a) => (
                <p key={a} className="text-[#EF4444]">
                  {a}
                </p>
              ))}
              {s.incidents.items.map((i) => (
                <p key={i.id}>
                  Incident ({i.severity}): {i.title}
                </p>
              ))}
            </Section>
          </div>
          {data.generated_at && (
            <p className="text-[10px] font-mono text-[#6B6B6E]">
              Generated {new Date(data.generated_at).toLocaleString()}
              {data.freshness.age_seconds != null && ` · verified ${data.freshness.age_seconds}s ago`}
            </p>
          )}
        </div>
      )}
    </Card>
  );
}
