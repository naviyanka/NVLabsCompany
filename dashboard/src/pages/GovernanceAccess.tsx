import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, Lock, Unlock } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge, type BadgeVariant } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient } from '@/api/client';

const BASE = '/api/v1/governance';
export const LOCKDOWN_PHRASE = 'LOCKDOWN';
export const RELEASE_PHRASE = 'RELEASE LOCKDOWN';

interface Capability {
  id: string;
  name: string;
  category: string;
  risk: string;
  support: 'enforced' | 'approval_only' | 'display_only' | 'unsupported';
  state: string;
  explanation: string;
  source?: string | null;
}
interface AgentRow { id: string; name: string; role: string }
interface Restriction { id: string; kind: string; agent_id: string | null; reason: string; created_by: string }
interface Restrictions { lockdown: Restriction | null; isolated_agents: Restriction[] }
interface Grant {
  id: string; agent_id: string; tool_name: string; effect: string; status: string;
  expires_at: string; requested_by: string;
}
interface Attempt { id: string; agent_id: string; status: string; cancel_requested: boolean }
interface Turn { id: string; agent_id: string; status: string; cancel_requested: boolean }
interface AuditItem { id: string; action: string; actor: string | null; at: string | null }

const STATE_VARIANT: Record<string, BadgeVariant> = {
  allowed: 'success',
  inherited: 'success',
  temporarily_allowed: 'info',
  approval_required: 'warning',
  denied: 'danger',
  temporarily_denied: 'danger',
  unsupported: 'neutral',
};

const SUPPORT_LABEL: Record<Capability['support'], string> = {
  enforced: 'Enforced',
  approval_only: 'Approval only',
  display_only: 'Display only',
  unsupported: 'Not enforceable',
};

const label = (s: string) => s.replace(/_/g, ' ');

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : 'Request failed';
}

type Tab = 'access' | 'runtime' | 'grants' | 'audit';

export function GovernanceAccess() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('access');
  const [agentId, setAgentId] = useState('');
  const [reason, setReason] = useState('');
  const [lockOpen, setLockOpen] = useState(false);
  const [phrase, setPhrase] = useState('');

  const agents = useQuery({
    queryKey: ['gov', 'agents'],
    queryFn: () => apiClient.get<{ items: AgentRow[] }>(`${BASE}/agents`),
  });
  const selected = agentId || agents.data?.items[0]?.id || '';
  const restrictions = useQuery({
    queryKey: ['gov', 'restrictions'],
    queryFn: () => apiClient.get<Restrictions>(`${BASE}/restrictions`),
  });
  const access = useQuery({
    queryKey: ['gov', 'access', selected],
    enabled: tab === 'access' && !!selected,
    queryFn: () =>
      apiClient.get<{ capabilities: Capability[] }>(`${BASE}/agents/${selected}/effective-access`),
  });
  const runtime = useQuery({
    queryKey: ['gov', 'runtime'],
    enabled: tab === 'runtime',
    queryFn: () => apiClient.get<{ attempts: Attempt[]; turns: Turn[] }>(`${BASE}/runtime`),
  });
  const grants = useQuery({
    queryKey: ['gov', 'grants'],
    enabled: tab === 'grants',
    queryFn: () => apiClient.get<{ items: Grant[] }>(`${BASE}/grants`),
  });
  const audit = useQuery({
    queryKey: ['gov', 'audit'],
    enabled: tab === 'audit',
    queryFn: () => apiClient.get<{ items: AuditItem[] }>(`${BASE}/audit`),
  });

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      apiClient.post<unknown>(`${BASE}${path}`, body),
    onSuccess: () => {
      setLockOpen(false);
      setPhrase('');
      setReason('');
      qc.invalidateQueries({ queryKey: ['gov'] });
    },
  });

  const locked = restrictions.data?.lockdown ?? null;
  const reasonOk = reason.trim().length >= 5;
  const need = locked ? RELEASE_PHRASE : LOCKDOWN_PHRASE;
  const isolated = restrictions.data?.isolated_agents.find((r) => r.agent_id === selected);
  const caps = access.data?.capabilities ?? [];
  const byCategory = caps.reduce<Record<string, Capability[]>>((acc, c) => {
    (acc[c.category] ??= []).push(c);
    return acc;
  }, {});
  const reasonField = (
    <input
      aria-label="Reason"
      className="w-full rounded-[6px] bg-transparent border border-white/[0.12] px-3 py-2 text-sm"
      placeholder="Reason (at least 5 characters)"
      value={reason}
      onChange={(e) => setReason(e.target.value)}
    />
  );

  return (
    <div className="space-y-6 p-6">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold flex items-center gap-2">
            <ShieldAlert className="h-5 w-5" /> Access Governance
          </h1>
          <p className="text-sm text-[#A8A8AB]">
            What each agent can do, decided by the same engine that enforces it.
          </p>
        </div>
        <Button variant={locked ? 'secondary' : 'danger'} onClick={() => setLockOpen(true)}
          icon={locked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}>
          {locked ? 'Release lockdown' : 'Lock down company'}
        </Button>
      </header>

      {locked && (
        <div role="alert" className="rounded-[8px] border border-[#EF4444]/40 bg-[#EF4444]/10 p-3 text-sm">
          Company lockdown is active: {locked.reason}. Write and external tools are denied for every agent.
        </div>
      )}
      {act.error && <div role="alert" className="text-sm text-[#EF4444]">{errorText(act.error)}</div>}

      <nav className="flex gap-2" aria-label="Sections">
        {(['access', 'runtime', 'grants', 'audit'] as Tab[]).map((t) => (
          <Button key={t} size="sm" variant={tab === t ? 'primary' : 'ghost'} onClick={() => setTab(t)}>
            {t === 'access' ? 'Effective access' : t.charAt(0).toUpperCase() + t.slice(1)}
          </Button>
        ))}
      </nav>

      {tab === 'access' && (
        <Card>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <select aria-label="Agent" className="rounded-[6px] bg-[#141416] border border-white/[0.12] px-3 py-2 text-sm"
              value={selected} onChange={(e) => setAgentId(e.target.value)}>
              {(agents.data?.items ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            {isolated ? (
              <>
                <Badge variant="danger">Isolated: {isolated.reason}</Badge>
                {reasonField}
                <Button size="sm" variant="secondary" disabled={!reasonOk}
                  onClick={() => act.mutate({ path: `/agents/${selected}/isolate/release`, body: { reason } })}>
                  Release isolation
                </Button>
              </>
            ) : (
              selected && (
                <>
                  {reasonField}
                  <Button size="sm" variant="danger" disabled={!reasonOk}
                    onClick={() => act.mutate({ path: `/agents/${selected}/isolate`, body: { reason } })}>
                    Isolate agent
                  </Button>
                </>
              )
            )}
          </div>
          {Object.entries(byCategory).map(([category, rows]) => (
            <section key={category} className="mb-6">
              <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-[#A8A8AB]">{label(category)}</h2>
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[#A8A8AB]">
                    <th className="py-1">Capability</th><th>Risk</th><th>Support</th><th>Now</th><th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id} data-testid={`cap-${c.id}`} className="border-t border-white/[0.06] align-top">
                      <td className="py-2">{c.name}</td>
                      <td>{c.risk}</td>
                      <td>{SUPPORT_LABEL[c.support]}</td>
                      <td><Badge variant={STATE_VARIANT[c.state] ?? 'neutral'}>{label(c.state)}</Badge></td>
                      <td className="text-[#A8A8AB]">{c.explanation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          {access.isError && <p role="alert" className="text-sm text-[#EF4444]">{errorText(access.error)}</p>}
        </Card>
      )}

      {tab === 'runtime' && (
        <Card>
          <div className="mb-3">{reasonField}</div>
          {[...(runtime.data?.attempts ?? []).map((a) => ({ ...a, kind: 'attempts' })),
            ...(runtime.data?.turns ?? []).map((a) => ({ ...a, kind: 'turns' }))].map((w) => (
            <div key={w.id} className="flex items-center justify-between border-t border-white/[0.06] py-2 text-sm">
              <span>{w.kind === 'attempts' ? 'Attempt' : 'Turn'} {w.id.slice(0, 8)} · {w.status}
                {w.cancel_requested ? ' · cancelling' : ''}</span>
              <Button size="xs" variant="danger" disabled={!reasonOk || w.cancel_requested}
                onClick={() => act.mutate({ path: `/runtime/${w.kind}/${w.id}/cancel`, body: { reason } })}>
                Cancel
              </Button>
            </div>
          ))}
          {runtime.data && !runtime.data.attempts.length && !runtime.data.turns.length && (
            <p className="text-sm text-[#A8A8AB]">Nothing is running.</p>
          )}
        </Card>
      )}

      {tab === 'grants' && (
        <Card>
          <div className="mb-3">{reasonField}</div>
          {(grants.data?.items ?? []).map((g) => (
            <div key={g.id} className="flex items-center justify-between border-t border-white/[0.06] py-2 text-sm">
              <span>{g.effect} {g.tool_name} · {label(g.status)} · until {g.expires_at.slice(0, 16)} · by {g.requested_by}</span>
              <span className="flex gap-2">
                {g.status === 'pending_approval' && (
                  <>
                    <Button size="xs" onClick={() => act.mutate({ path: `/grants/${g.id}/approve`, body: { note: reason } })}>
                      Approve
                    </Button>
                    <Button size="xs" variant="secondary" onClick={() => act.mutate({ path: `/grants/${g.id}/reject`, body: { note: reason } })}>
                      Reject
                    </Button>
                  </>
                )}
                {(g.status === 'active' || g.status === 'pending_approval') && (
                  <Button size="xs" variant="danger" disabled={!reasonOk}
                    onClick={() => act.mutate({ path: `/grants/${g.id}/revoke`, body: { reason } })}>
                    Revoke
                  </Button>
                )}
              </span>
            </div>
          ))}
          {grants.data && !grants.data.items.length && (
            <p className="text-sm text-[#A8A8AB]">No temporary grants.</p>
          )}
        </Card>
      )}

      {tab === 'audit' && (
        <Card>
          {(audit.data?.items ?? []).map((i) => (
            <div key={i.id} className="flex justify-between border-t border-white/[0.06] py-2 text-sm">
              <span>{i.action.replace('governance.', '')}</span>
              <span className="text-[#A8A8AB]">{i.actor} · {i.at?.slice(0, 19)}</span>
            </div>
          ))}
          {audit.data && !audit.data.items.length && (
            <p className="text-sm text-[#A8A8AB]">No governance changes yet.</p>
          )}
        </Card>
      )}

      <Modal isOpen={lockOpen} onClose={() => setLockOpen(false)}
        title={locked ? 'Release company lockdown' : 'Lock down company'}>
        <div className="space-y-3">
          <p className="text-sm">
            {locked
              ? 'Agents can use write and external tools again.'
              : 'Every agent loses write and external tools until a human administrator releases it.'}
          </p>
          {reasonField}
          <input aria-label="Confirmation" className="w-full rounded-[6px] bg-transparent border border-white/[0.12] px-3 py-2 text-sm"
            placeholder={`Type ${need} to confirm`} value={phrase} onChange={(e) => setPhrase(e.target.value)} />
          <Button variant={locked ? 'primary' : 'danger-solid'} disabled={!reasonOk || phrase.trim() !== need}
            loading={act.isPending}
            onClick={() => act.mutate({ path: locked ? '/lockdown/release' : '/lockdown', body: { reason, confirm: phrase.trim() } })}>
            {locked ? 'Release' : 'Lock down'}
          </Button>
        </div>
      </Modal>
    </div>
  );
}
