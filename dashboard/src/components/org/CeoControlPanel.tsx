/**
 * CeoControlPanel — the company's designated CEO.
 *
 * Reads GET /api/v1/organization/ceo (`nexus/services/ceo_service.py`): the CEO,
 * whether its backend can run governed CEO tools, the snapshot it answers from,
 * recent executive memory and pending human approvals. Appointing, replacing and
 * removing the CEO are human-administrator actions; the server enforces that.
 */

import { apiClient } from '@/api/client';
import { Badge } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import type { Agent } from '@/types/agent';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { FRESHNESS_BADGE, type SnapshotEnvelope } from './OrganizationSnapshotPanel';

interface MemoryItem {
  id: string;
  type: string;
  content: string;
  status: string;
  created_at: string;
}

export interface CeoStatus {
  ceo: { id: string; name: string; title: string; backend: string | null } | null;
  ceo_tools_available: boolean;
  ceo_tools_unavailable_reason: string | null;
  snapshot: Pick<SnapshotEnvelope, 'version' | 'generated_at' | 'freshness' | 'last_refresh_error'>;
  pending_approvals: { id: string; type: string; created_at: string | null }[];
  memory: MemoryItem[];
}

const PATH = '/api/v1/organization/ceo';

export function CeoControlPanel({ agents }: { agents: Agent[] }) {
  const [data, setData] = useState<CeoStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [choice, setChoice] = useState('');

  const run = useCallback(async (request?: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      if (request) await request();
      setData(await apiClient.get<CeoStatus>(PATH));
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load the CEO');
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    void run();
  }, [run]);

  const ceo = data?.ceo;
  const snap = data?.snapshot;
  return (
    <Card
      header={
        <span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">
          CEO{ceo && ` · ${ceo.name}`}
        </span>
      }
    >
      {error && <p role="alert" className="mb-2 text-xs text-[#EF4444]">{error}</p>}
      <div className="space-y-3 text-xs text-[#A1A1A6]">
        <div className="flex flex-wrap items-center gap-2">
          <select
            aria-label="CEO agent"
            className="rounded-md border border-[#222] bg-[#101012] px-2 py-1 text-xs"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
          >
            <option value="">Select an agent</option>
            {agents
              .filter((a) => a.id !== ceo?.id)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name} ({a.title})
                </option>
              ))}
          </select>
          <Button
            size="sm"
            variant="secondary"
            disabled={busy || !choice}
            onClick={() => void run(() => apiClient.put(PATH, { agent_id: choice }))}
          >
            {ceo ? 'Replace CEO' : 'Appoint CEO'}
          </Button>
          {ceo && (
            <>
              <Button size="sm" variant="secondary" disabled={busy} onClick={() => void run(() => apiClient.delete(PATH))}>
                Remove CEO
              </Button>
              <Link to={`/agents/${ceo.id}`} className="text-[#FFB020] underline">
                Open CEO chat
              </Link>
            </>
          )}
        </div>

        {data && !ceo && <p>No CEO designated.</p>}
        {ceo && (
          <p data-testid="ceo-backend">
            Backend: {ceo.backend ?? 'none'} ·{' '}
            {data.ceo_tools_available ? 'governed CEO tools available' : 'chat only, no CEO tools'}
            {data.ceo_tools_unavailable_reason && ` (${data.ceo_tools_unavailable_reason})`}
          </p>
        )}
        {snap && (
          <p className="flex items-center gap-2" data-testid="ceo-snapshot">
            Snapshot {snap.version != null ? `v${snap.version}` : 'not generated'}
            <Badge variant={FRESHNESS_BADGE[snap.freshness.status] ?? 'neutral'} dot>
              {snap.freshness.status}
            </Badge>
            {snap.last_refresh_error && (
              <span className="text-[#EF4444]">Last refresh failed: {snap.last_refresh_error.message}</span>
            )}
          </p>
        )}
        {data && (
          <div data-testid="ceo-approvals">
            <p className="font-mono uppercase text-[#6B6B6E]">
              {data.pending_approvals.length} pending human approval(s)
            </p>
            {data.pending_approvals.map((a) => (
              <p key={a.id}>{a.type}</p>
            ))}
          </div>
        )}
        {data && (
          <div data-testid="ceo-memory">
            <p className="font-mono uppercase text-[#6B6B6E]">Recent executive memory</p>
            {data.memory.length === 0 && <p>None.</p>}
            {data.memory.map((m) => (
              <p key={m.id}>
                [{m.type}] {m.content}
              </p>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
