import { useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import {
  BASE, CapName, CopyId, DecisionBadge, Field, Findings, StateLine, inputClass, label, withMeta,
  type AgentRow, type CapMeta, type Finding, type Rule,
} from './shared';

interface Capability extends CapMeta { name: string; category: string; support: string }
interface Decision {
  state: string; decision: string; code: string; explanation: string; plain_explanation?: string;
  source: string | null;
  approval: { required?: boolean; level?: number } | null; backend_support: string;
  steps: { label: string; result: string }[]; blockers: string[];
  validity: { expires_at: string; uses_left: number | null } | null;
}
interface SimResult {
  current: Decision; proposed: Decision | null; findings: Finding[]; notes: string[];
}
interface DraftRow { id: string; reason: string; base_version: number; stale: boolean; rules: Rule[] }

function DecisionView({ title, d }: { title: string; d: Decision }) {
  return (
    <section aria-label={title} className="space-y-2 rounded-[8px] border border-white/[0.08] p-3">
      <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">
        {title} <DecisionBadge value={d.decision} />
      </h3>
      <p className="text-sm">{d.plain_explanation ?? d.explanation}</p>
      <details className="text-xs text-[#A8A8AB]">
        <summary className="cursor-pointer">Technical details</summary>
        <dl className="mt-1 grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 break-words [overflow-wrap:anywhere]">
          <dt>Reason code</dt><dd><code>{d.code}</code></dd>
          <dt>Engine message</dt><dd>{d.explanation}</dd>
        </dl>
      </details>
      <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-[#A8A8AB]">Decided by</dt><dd>{d.source ?? 'no rule matched'}</dd>
        <dt className="text-[#A8A8AB]">Approval</dt>
        <dd>{d.approval?.required ? `Required (autonomy level ${d.approval.level})` : 'Not required'}</dd>
        {d.validity && (
          <>
            <dt className="text-[#A8A8AB]">Grant valid until</dt>
            <dd>{d.validity.expires_at.slice(0, 16)}
              {d.validity.uses_left !== null && ` · ${d.validity.uses_left} use(s) left`}</dd>
          </>
        )}
      </dl>
      <ol aria-label="Order the engine checks" className="list-decimal space-y-0.5 pl-5 text-sm">
        {d.steps.map((s) => (
          <li key={s.label} className={s.result === 'not reached' ? 'text-[#A8A8AB]' : ''}>
            {s.label}: <strong>{s.result === 'decided' ? 'decided here' : s.result}</strong>
          </li>
        ))}
      </ol>
      {!!d.blockers.length && (
        <ul aria-label="Blockers" className="space-y-0.5 text-sm">
          {d.blockers.map((b) => <li key={b}><Badge variant="warning">BLOCKER</Badge> {b}</li>)}
        </ul>
      )}
    </section>
  );
}

export function SimulatorPanel({ agents, defaultAgentId }: { agents: AgentRow[]; defaultAgentId: string }) {
  const [agentId, setAgentId] = useState('');
  const [capId, setCapId] = useState('');
  const [sessionId, setSessionId] = useState('');
  const [draftId, setDraftId] = useState('');

  const catalog = useQuery({
    queryKey: ['gov', 'catalog'],
    queryFn: () => apiClient.get<{ capabilities: Capability[] }>(`${BASE}/catalog`),
  });
  const drafts = useQuery({
    queryKey: ['gov', 'drafts', 'open'],
    queryFn: () => apiClient.get<{ items: DraftRow[] }>(`${BASE}/drafts`, { status: 'draft', limit: 50 }),
  });
  const caps = (catalog.data?.capabilities ?? []).map(withMeta);
  const agent = agentId || defaultAgentId;
  const capability = caps.find((c) => c.id === (capId || caps[0]?.id));
  const draft = drafts.data?.items.find((d) => d.id === draftId);
  const sessionOk = !sessionId || /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(sessionId.trim());

  const run = useMutation({
    mutationFn: () =>
      apiClient.post<SimResult>(`${BASE}/simulate`, {
        agent_id: agent,
        capability_id: capability?.id,
        ...(sessionId.trim() ? { session_id: sessionId.trim() } : {}),
        ...(draft ? { proposed_rules: draft.rules } : {}),
      }),
  });

  const byCategory = caps.reduce<Record<string, Capability[]>>((acc, c) => {
    (acc[c.category] ??= []).push(c);
    return acc;
  }, {});

  return (
    <Card>
      <p role="note" className="mb-3 rounded-[6px] border border-white/[0.12] p-2 text-sm">
        A simulation only asks the policy engine what it would decide. It calls no tool, spends no
        temporary grant and has no external effect.
      </p>
      <form className="mb-4 flex flex-wrap gap-3" onSubmit={(e) => { e.preventDefault(); run.mutate(); }}>
        <Field name="Simulated agent">
          <select className={inputClass} value={agent} onChange={(e) => setAgentId(e.target.value)}>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        <Field name="Capability">
          <select className={inputClass} value={capability?.id ?? ''} onChange={(e) => setCapId(e.target.value)}>
            {Object.entries(byCategory).map(([cat, rows]) => (
              <optgroup key={cat} label={label(cat)}>
                {rows.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.display_name} ({c.id}){c.support === 'unsupported' ? ' (not enforceable)' : ''}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </Field>
        <Field name="Policy to test">
          <select className={inputClass} value={draftId} onChange={(e) => setDraftId(e.target.value)}>
            <option value="">Active policy</option>
            {(drafts.data?.items ?? []).map((d) => (
              <option key={d.id} value={d.id}>
                Draft: {d.reason.slice(0, 40)}{d.stale ? ' (stale)' : ''}
              </option>
            ))}
          </select>
        </Field>
        <Field name="Session (optional)" hint="Session is the only scope the engine enforces. Task and resource scopes are not enforceable, so they are not offered.">
          <input className={inputClass} value={sessionId} placeholder="Session id"
            aria-invalid={!sessionOk} onChange={(e) => setSessionId(e.target.value)} />
        </Field>
        <div className="flex items-end">
          <Button type="submit" loading={run.isPending} disabled={!capability || !agent || !sessionOk}>
            Simulate
          </Button>
        </div>
      </form>
      {capability && (
        <div aria-label="Selected capability" className="mb-3 flex flex-wrap items-start gap-2 text-sm">
          <CapName cap={capability} />
          <CopyId id={capability.id} />
          {capability.support === 'unsupported' && (
            <Badge variant="neutral">Not enforceable: NEXUS cannot currently enforce this capability.</Badge>
          )}
        </div>
      )}
      {!!capability?.scope_schema?.conditions?.length && (
        <p className="mb-3 text-xs text-[#A8A8AB]">
          Policy conditions the engine can match for this capability: {capability.scope_schema.conditions.map(label).join(', ')}.
        </p>
      )}
      {!sessionOk && <p role="alert" className="text-sm text-[#EF4444]">Session must be a valid id.</p>}
      <StateLine loading={catalog.isLoading} error={catalog.error ?? run.error} emptyText="" />
      {run.data && (
        <div className="space-y-3" aria-live="polite">
          <DecisionView title="Decision now" d={run.data.current} />
          {run.data.proposed && <DecisionView title="Decision with the draft" d={run.data.proposed} />}
          <Findings items={run.data.findings} />
          <ul className="space-y-0.5 text-xs text-[#A8A8AB]">
            {run.data.notes.map((n) => <li key={n}>{n}</li>)}
          </ul>
        </div>
      )}
    </Card>
  );
}
