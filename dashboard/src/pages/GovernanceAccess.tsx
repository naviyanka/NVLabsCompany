import { Fragment, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ShieldAlert, Lock, Unlock } from 'lucide-react';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge, type BadgeVariant } from '@/components/common/Badge';
import { Modal } from '@/components/common/Modal';
import { apiClient } from '@/api/client';
import { SimulatorPanel } from '@/components/governance/SimulatorPanel';
import { PolicyDrafts } from '@/components/governance/PolicyDrafts';
import { PolicyVersions } from '@/components/governance/PolicyVersions';
import { PresetsPanel } from '@/components/governance/PresetsPanel';
import { GrantForm } from '@/components/governance/GrantForm';
import {
  BASE, PAGE, ConfirmModal, CopyId, Pager, StateLine, errorText, firstSentence, label,
  usePermission, useToolText, withMeta,
} from '@/components/governance/shared';

export const LOCKDOWN_PHRASE = 'LOCKDOWN';
export const RELEASE_PHRASE = 'RELEASE LOCKDOWN';

interface Capability {
  id: string;
  name: string;
  display_name?: string;
  description?: string;
  limitations?: string | null;
  examples?: string[];
  plain_explanation?: string;
  category: string;
  risk: string;
  support: 'enforced' | 'approval_only' | 'display_only' | 'unsupported';
  state: string;
  explanation: string;
  source?: string | null;
  code?: string;
  tool_name?: string | null;
  inheritance_source?: string | null;
  conditions?: Record<string, unknown> | null;
  approval?: { required: boolean; level?: number };
  validity?: { expires_at: string; uses_left: number | null } | null;
  last_used?: string | null;
}
interface AgentRow { id: string; name: string; role: string }
interface Confirm { title: string; text: string; path: string; body: unknown; action: string }
interface Restriction { id: string; kind: string; agent_id: string | null; reason: string; created_by: string }
interface Restrictions { lockdown: Restriction | null; isolated_agents: Restriction[] }
interface Grant {
  id: string; agent_id: string; tool_name: string; effect: string; status: string;
  expires_at: string; requested_by: string;
}
interface Attempt { id: string; agent_id: string; status: string; cancel_requested: boolean }
interface Turn { id: string; agent_id: string; status: string; cancel_requested: boolean }
interface AuditItem {
  id: string; action: string; actor: string | null; at: string | null; details?: Record<string, unknown> | null;
}

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

type Tab = 'access' | 'simulator' | 'policy' | 'autonomy' | 'runtime' | 'grants' | 'audit';
const TABS: [Tab, string][] = [
  ['access', 'Effective access'], ['simulator', 'Simulator'], ['policy', 'Policy'],
  ['autonomy', 'Autonomy presets'], ['runtime', 'Runtime'], ['grants', 'Grants'], ['audit', 'Audit'],
];

export function GovernanceAccess() {
  const qc = useQueryClient();
  const permission = usePermission();
  const canEdit = permission === 'write';
  const [tab, setTab] = useState<Tab>('access');
  const [agentId, setAgentId] = useState('');
  const [reason, setReason] = useState('');
  const [lockOpen, setLockOpen] = useState(false);
  const [phrase, setPhrase] = useState('');
  const [policyView, setPolicyView] = useState<'drafts' | 'versions'>('drafts');
  const [confirm, setConfirm] = useState<Confirm | null>(null);
  const [grantOffset, setGrantOffset] = useState(0);
  const [auditOffset, setAuditOffset] = useState(0);
  const [agentQuery, setAgentQuery] = useState('');
  const [openCap, setOpenCap] = useState<string | null>(null);
  const [capQuery, setCapQuery] = useState('');
  const toolText = useToolText();

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
    queryKey: ['gov', 'grants', grantOffset],
    enabled: tab === 'grants',
    queryFn: () => apiClient.get<{ items: Grant[] }>(`${BASE}/grants`, { limit: PAGE, offset: grantOffset }),
  });
  const audit = useQuery({
    queryKey: ['gov', 'audit', auditOffset],
    enabled: tab === 'audit',
    queryFn: () => apiClient.get<{ items: AuditItem[] }>(`${BASE}/audit`, { limit: PAGE, offset: auditOffset }),
  });

  const act = useMutation({
    mutationFn: ({ path, body }: { path: string; body: unknown }) =>
      apiClient.post<unknown>(`${BASE}${path}`, body),
    onSuccess: () => {
      setLockOpen(false);
      setConfirm(null);
      setPhrase('');
      setReason('');
      qc.invalidateQueries({ queryKey: ['gov'] });
    },
  });

  const locked = restrictions.data?.lockdown ?? null;
  const reasonOk = reason.trim().length >= 5;
  const need = locked ? RELEASE_PHRASE : LOCKDOWN_PHRASE;
  const isolated = restrictions.data?.isolated_agents.find((r) => r.agent_id === selected);
  const nameOf = (c: Capability) => withMeta(c).display_name;
  const descOf = (c: Capability) => withMeta(c).description;
  const needle = capQuery.trim().toLowerCase();
  // Search is display only: it matches what a person might type, never decides access.
  const caps = (access.data?.capabilities ?? []).filter((c) =>
    !needle || [nameOf(c), descOf(c), c.id, c.category, label(c.category)].some((t) => t.toLowerCase().includes(needle)));
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
        {canEdit && (
          <Button variant={locked ? 'secondary' : 'danger'} onClick={() => setLockOpen(true)}
            icon={locked ? <Unlock className="h-4 w-4" /> : <Lock className="h-4 w-4" />}>
            {locked ? 'Release lockdown' : 'Lock down company'}
          </Button>
        )}
      </header>

      {permission === 'read' && (
        <p role="note" className="rounded-[8px] border border-white/[0.12] p-3 text-sm">
          View only. Only a human administrator can change governance.
        </p>
      )}
      {permission === 'unknown' && (
        <p role="note" className="rounded-[8px] border border-white/[0.12] p-3 text-sm">
          Could not confirm your permission, so every change control is off. Reload to try again.
        </p>
      )}

      {locked && (
        <div role="alert" className="rounded-[8px] border border-[#EF4444]/40 bg-[#EF4444]/10 p-3 text-sm">
          Company lockdown is active: {locked.reason}. Write and external tools are denied for every agent.
        </div>
      )}
      {act.error && <div role="alert" className="text-sm text-[#EF4444]">{errorText(act.error)}</div>}

      <nav className="flex flex-wrap gap-2" aria-label="Sections">
        {TABS.map(([t, text]) => (
          <Button key={t} size="sm" variant={tab === t ? 'primary' : 'ghost'} aria-current={tab === t ? 'page' : undefined}
            onClick={() => setTab(t)}>
            {text}
          </Button>
        ))}
      </nav>

      {tab === 'access' && (
        <Card>
          <div className="mb-4 flex flex-wrap items-center gap-3">
            <input aria-label="Search agents" type="search" placeholder="Search agents"
              className="rounded-[6px] bg-transparent border border-white/[0.12] px-3 py-2 text-sm"
              value={agentQuery} onChange={(e) => setAgentQuery(e.target.value)} />
            <input aria-label="Search capabilities" type="search" placeholder="Search capabilities"
              className="min-w-[16rem] rounded-[6px] bg-transparent border border-white/[0.12] px-3 py-2 text-sm"
              value={capQuery} onChange={(e) => setCapQuery(e.target.value)} />
            <select aria-label="Agent" className="rounded-[6px] bg-[#141416] border border-white/[0.12] px-3 py-2 text-sm"
              value={selected} onChange={(e) => setAgentId(e.target.value)}>
              {(agents.data?.items ?? [])
                .filter((a) => a.id === selected || `${a.name} ${a.role}`.toLowerCase().includes(agentQuery.trim().toLowerCase()))
                .map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
            {isolated ? (
              !canEdit ? <Badge variant="danger">Isolated: {isolated.reason}</Badge> :
              <>
                <Badge variant="danger">Isolated: {isolated.reason}</Badge>
                {reasonField}
                <Button size="sm" variant="secondary" disabled={!reasonOk}
                  onClick={() => setConfirm({
                    title: 'Release agent isolation', action: 'Release isolation',
                    text: 'The agent can use write and external tools again.',
                    path: `/agents/${selected}/isolate/release`, body: { reason },
                  })}>
                  Release isolation
                </Button>
              </>
            ) : (
              selected && canEdit && (
                <>
                  {reasonField}
                  <Button size="sm" variant="danger" disabled={!reasonOk}
                    onClick={() => setConfirm({
                      title: 'Isolate agent', action: 'Isolate agent',
                      text: 'The agent loses write and external tools until a human administrator releases it.',
                      path: `/agents/${selected}/isolate`, body: { reason },
                    })}>
                    Isolate agent
                  </Button>
                </>
              )
            )}
          </div>
          {Object.entries(byCategory).map(([category, rows]) => (
            <section key={category} className="mb-6">
              <h2 className="mb-2 text-sm font-medium uppercase tracking-wide text-[#A8A8AB]">{label(category)}</h2>
              <table className="w-full table-fixed text-sm">
                <caption className="sr-only">{label(category)} capabilities</caption>
                <thead>
                  <tr className="text-left text-[#A8A8AB]">
                    <th scope="col" className="w-[38%] py-1">Capability</th><th scope="col" className="w-[8%]">Risk</th>
                    <th scope="col" className="w-[12%]">Support</th><th scope="col" className="w-[14%]">Now</th>
                    <th scope="col" className="w-[28%]">Why</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <Fragment key={c.id}>
                      <tr data-testid={`cap-${c.id}`} className="border-t border-white/[0.06] align-top break-words [overflow-wrap:anywhere]">
                        <td className="py-2 pr-2">
                          <button type="button" className="text-left font-medium underline decoration-dotted"
                            aria-expanded={openCap === c.id}
                            aria-label={`${nameOf(c)}, ${label(c.state)}, ${c.risk} risk, ${SUPPORT_LABEL[c.support]}`}
                            onClick={() => setOpenCap(openCap === c.id ? null : c.id)}>
                            {nameOf(c)}
                          </button>
                          <span className="block text-xs text-[#A8A8AB]">{firstSentence(descOf(c))}</span>
                          <code className="block font-mono text-[11px] text-[#8A8A8E]">{c.id}</code>
                        </td>
                        <td>{c.risk}</td>
                        <td>{SUPPORT_LABEL[c.support]}</td>
                        <td><Badge variant={STATE_VARIANT[c.state] ?? 'neutral'}>{label(c.state)}</Badge></td>
                        <td className="text-[#A8A8AB]">{c.plain_explanation ?? c.explanation}</td>
                      </tr>
                      {openCap === c.id && (
                        <tr className="bg-white/[0.02]">
                          <td colSpan={5} className="px-2 py-2">
                            <dl aria-label={`${nameOf(c)} details`}
                              className="grid grid-cols-[10rem_1fr] gap-x-3 gap-y-1 break-words text-xs [overflow-wrap:anywhere]">
                              <dt>What it does</dt><dd>{descOf(c)}</dd>
                              {c.limitations && <><dt>Limits</dt><dd>{c.limitations}</dd></>}
                              {!!c.examples?.length && <><dt>Examples</dt><dd>{c.examples.join('; ')}</dd></>}
                              <dt>Technical ID</dt>
                              <dd><code className="font-mono">{c.id}</code> <CopyId id={c.id} /></dd>
                              <dt>Reason code</dt><dd>{c.code ?? 'none'}</dd>
                              <dt>Engine message</dt><dd>{c.explanation}</dd>
                              <dt>Source</dt><dd>{c.source ?? 'none'}</dd>
                              <dt>Inherited from</dt><dd>{c.inheritance_source ?? 'none'}</dd>
                              <dt>Conditions</dt><dd>{c.conditions ? JSON.stringify(c.conditions) : 'none'}</dd>
                              <dt>Approval</dt><dd>{c.approval?.required ? 'required' : 'not required'}</dd>
                              <dt>Grant validity</dt>
                              <dd>{c.validity ? `until ${c.validity.expires_at.slice(0, 16)}, uses left ${c.validity.uses_left ?? 'unlimited'}` : 'none'}</dd>
                              <dt>Last used</dt><dd>{c.last_used?.slice(0, 16) ?? 'never'}</dd>
                            </dl>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </section>
          ))}
          {!!needle && !caps.length && !access.isLoading && (
            <p role="status" className="text-sm text-[#A8A8AB]">No capability matches “{capQuery.trim()}”.</p>
          )}
          <StateLine loading={access.isLoading} error={access.error} emptyText="" />
        </Card>
      )}

      {tab === 'simulator' && <SimulatorPanel agents={agents.data?.items ?? []} defaultAgentId={selected} />}

      {tab === 'policy' && (
        <div className="space-y-4">
          <nav className="flex gap-2" aria-label="Policy views">
            {(['drafts', 'versions'] as const).map((v) => (
              <Button key={v} size="sm" variant={policyView === v ? 'primary' : 'ghost'}
                aria-current={policyView === v ? 'page' : undefined} onClick={() => setPolicyView(v)}>
                {v === 'drafts' ? 'Drafts' : 'Versions'}
              </Button>
            ))}
          </nav>
          {policyView === 'drafts' ? <PolicyDrafts agents={agents.data?.items ?? []} /> : <PolicyVersions />}
        </div>
      )}

      {tab === 'autonomy' && <PresetsPanel agents={agents.data?.items ?? []} defaultAgentId={selected} />}

      {tab === 'runtime' && (
        <Card>
          {canEdit && <div className="mb-3">{reasonField}</div>}
          {[...(runtime.data?.attempts ?? []).map((a) => ({ ...a, kind: 'attempts' })),
            ...(runtime.data?.turns ?? []).map((a) => ({ ...a, kind: 'turns' }))].map((w) => (
            <div key={w.id} className="flex items-center justify-between border-t border-white/[0.06] py-2 text-sm">
              <span>{w.kind === 'attempts' ? 'Attempt' : 'Turn'} {w.id.slice(0, 8)} · {w.status}
                {w.cancel_requested ? ' · cancelling' : ''}</span>
              {canEdit && (
                <Button size="xs" variant="danger" disabled={!reasonOk || w.cancel_requested}
                  onClick={() => act.mutate({ path: `/runtime/${w.kind}/${w.id}/cancel`, body: { reason } })}>
                  Cancel
                </Button>
              )}
            </div>
          ))}
          <StateLine loading={runtime.isLoading} error={runtime.error}
            empty={!!runtime.data && !runtime.data.attempts.length && !runtime.data.turns.length}
            emptyText="Nothing is running." />
        </Card>
      )}

      {tab === 'grants' && (
        <Card>
          {canEdit && <GrantForm agents={agents.data?.items ?? []} />}
          {canEdit && <div className="mb-3">{reasonField}</div>}
          {(grants.data?.items ?? []).map((g) => (
            <div key={g.id} className="flex items-center justify-between border-t border-white/[0.06] py-2 text-sm">
              <span className="min-w-0 break-words">{g.effect} {toolText(g.tool_name)} · {label(g.status)} · until {g.expires_at.slice(0, 16)} · by {g.requested_by}</span>
              <span className="flex gap-2">
                {canEdit && g.status === 'pending_approval' && (
                  <>
                    <Button size="xs" onClick={() => act.mutate({ path: `/grants/${g.id}/approve`, body: { note: reason } })}>
                      Approve
                    </Button>
                    <Button size="xs" variant="secondary" onClick={() => act.mutate({ path: `/grants/${g.id}/reject`, body: { note: reason } })}>
                      Reject
                    </Button>
                  </>
                )}
                {canEdit && (g.status === 'active' || g.status === 'pending_approval') && (
                  <Button size="xs" variant="danger" disabled={!reasonOk}
                    onClick={() => setConfirm({
                      title: 'Revoke temporary grant', action: 'Revoke grant',
                      text: `${g.effect} ${toolText(g.tool_name)} stops applying at once.`,
                      path: `/grants/${g.id}/revoke`, body: { reason },
                    })}>
                    Revoke
                  </Button>
                )}
              </span>
            </div>
          ))}
          <StateLine loading={grants.isLoading} error={grants.error}
            empty={!!grants.data && !grants.data.items.length} emptyText="No temporary grants." />
          <Pager offset={grantOffset} count={grants.data?.items.length ?? 0} onChange={setGrantOffset} />
        </Card>
      )}

      {tab === 'audit' && (
        <Card>
          {(audit.data?.items ?? []).map((i) => (
            <div key={i.id} className="flex justify-between border-t border-white/[0.06] py-2 text-sm">
              <span className="min-w-0 break-words">{i.action.replace('governance.', '')}
                {typeof i.details?.tool_name === 'string' && <> · {toolText(i.details.tool_name)}</>}</span>
              <span className="text-[#A8A8AB]">{i.actor} · {i.at?.slice(0, 19)}</span>
            </div>
          ))}
          <StateLine loading={audit.isLoading} error={audit.error}
            empty={!!audit.data && !audit.data.items.length} emptyText="No governance changes yet." />
          <Pager offset={auditOffset} count={audit.data?.items.length ?? 0} onChange={setAuditOffset} />
        </Card>
      )}

      <ConfirmModal open={canEdit && !!confirm} title={confirm?.title ?? ''} onClose={() => setConfirm(null)} danger
        confirmLabel={confirm?.action ?? 'Confirm'} pending={act.isPending}
        onConfirm={() => confirm && act.mutate({ path: confirm.path, body: confirm.body })}
        error={act.error && errorText(act.error)}>
        <p className="text-sm">{confirm?.text}</p>
        <p className="text-sm text-[#A8A8AB]">Reason: {reason}</p>
      </ConfirmModal>

      <Modal isOpen={canEdit && lockOpen} onClose={() => setLockOpen(false)}
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
