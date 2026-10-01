import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import { RuleEditor, newRule } from './RuleEditor';
import {
  BASE, PAGE, CapabilityDiff, ConfirmModal, Field, Findings, Pager, RuleDiff, StateLine,
  errorText, inputClass, isConflict, useCanEdit,
  type AgentRow, type Affects, type CapDiffData, type Finding, type Rule, type RuleDiffData,
} from './shared';

export interface Draft {
  id: string; status: string; base_version: number; stale: boolean; rules: Rule[]; reason: string;
  ticket_ref: string | null; created_by: string; reviewers: string[]; created_at: string | null;
  updated_at: string | null; diff: RuleDiffData; affects: Affects; loosens: boolean;
  findings: Finding[]; published_version: number | null;
}
interface Impact { capability_diff: CapDiffData; findings: Finding[] }

const STATUS_TEXT: Record<string, string> = { draft: 'Open', published: 'Published', discarded: 'Discarded' };

function PublishDialog({
  draft, agents, version, onClose,
}: { draft: Draft; agents: AgentRow[]; version: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [agentId, setAgentId] = useState(agents[0]?.id ?? '');
  const [reason, setReason] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const impact = useQuery({
    queryKey: ['gov', 'impact', draft.id, agentId],
    enabled: !!agentId,
    queryFn: () => apiClient.get<Impact>(`${BASE}/drafts/${draft.id}/impact`, { agent_id: agentId }),
  });
  const publish = useMutation({
    mutationFn: () =>
      apiClient.post<Draft>(`${BASE}/drafts/${draft.id}/publish`, {
        reason: reason.trim() || undefined, expected_version: version,
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['gov'] }); onClose(); },
  });
  const conflict = isConflict(publish.error);
  const findings = [...draft.findings, ...(impact.data?.findings ?? [])];
  const high = findings.filter((f) => f.severity === 'high');
  return (
    <ConfirmModal open title="Publish policy draft" onClose={onClose} confirmLabel="Publish" danger
      pending={publish.isPending} disabled={!reviewed || draft.stale || conflict}
      onConfirm={() => publish.mutate()}
      error={publish.error && (
        <>
          {conflict ? 'The rules changed while you were reviewing. Close this, reload the drafts and review again. ' : ''}
          {errorText(publish.error)}
        </>
      )}>
      <p className="text-sm">
        Publishing creates policy version {version + 1} from the exact rule changes below. Any change
        that loosens access must be published by someone other than its author, and by a listed
        reviewer if the draft names any. The server enforces this.
      </p>
      {draft.stale && (
        <p role="alert" className="text-sm text-[#EF4444]">
          This draft is based on version {draft.base_version} but the active policy is version {version}.
          It cannot be published. Create a new draft from the active policy.
        </p>
      )}
      <section aria-label="Exact rule changes"><h3 className="mb-1 text-sm font-medium">Exact rule changes</h3><RuleDiff diff={draft.diff} /></section>
      <p className="text-sm">
        Affects {draft.affects.all_agents ? 'every agent' : `${draft.affects.agent_ids.length} agent(s)`} and{' '}
        {draft.affects.capability_ids.length} capabilit{draft.affects.capability_ids.length === 1 ? 'y' : 'ies'}.
        {draft.loosens && <> <Badge variant="warning">LOOSENS ACCESS</Badge></>}
      </p>
      <Field name="Simulator summary for agent">
        <select className={inputClass} value={agentId} onChange={(e) => setAgentId(e.target.value)}>
          {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </Field>
      <StateLine loading={impact.isLoading} error={impact.error} emptyText="" />
      {impact.data && <CapabilityDiff diff={impact.data.capability_diff} />}
      <Findings items={findings} title="High-risk warnings" />
      {!!high.length && (
        <p role="alert" className="text-sm text-[#EF4444]">
          {high.length} high-severity finding(s). Findings are advisory and do not block publishing.
        </p>
      )}
      <Field name="Reason for publishing (optional)">
        <input className={inputClass} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
        I have reviewed the exact changes and I am not approving my own change.
      </label>
    </ConfirmModal>
  );
}

function Editor({
  draft, agents, version, onDone,
}: { draft: Draft | null; agents: AgentRow[]; version: number; onDone: () => void }) {
  const qc = useQueryClient();
  const canEdit = useCanEdit();
  const live = useQuery({
    queryKey: ['gov', 'policy'],
    enabled: !draft,
    queryFn: () => apiClient.get<{ rules: Rule[] }>(`${BASE}/policy`),
  });
  const [rules, setRules] = useState<Rule[] | null>(draft ? draft.rules : null);
  const [reason, setReason] = useState(draft?.reason ?? '');
  const [reviewers, setReviewers] = useState((draft?.reviewers ?? []).join(', '));
  const [publishing, setPublishing] = useState(false);
  const current = rules ?? live.data?.rules ?? [];
  const [saved, setSaved] = useState<Draft | null>(draft);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        rules: current, reason: reason.trim(), ticket_ref: saved?.ticket_ref ?? undefined,
        reviewers: reviewers.split(',').map((r) => r.trim()).filter(Boolean),
      };
      return saved
        ? apiClient.put<Draft>(`${BASE}/drafts/${saved.id}`, { ...body, expected_updated_at: saved.updated_at })
        : apiClient.post<Draft>(`${BASE}/drafts`, body);
    },
    onSuccess: (d) => { setSaved(d); setRules(d.rules); qc.invalidateQueries({ queryKey: ['gov', 'drafts'] }); },
  });
  const discard = useMutation({
    mutationFn: () => apiClient.post<Draft>(`${BASE}/drafts/${saved?.id}/discard`, {}),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['gov', 'drafts'] }); onDone(); },
  });
  const edit = (i: number, r: Rule) => setRules(current.map((x, j) => (j === i ? r : x)));
  const valid = reason.trim().length >= 5 && current.every((r) => r.name.trim());
  const open = canEdit && (!saved || saved.status === 'draft');
  return (
    <Card>
      <h2 className="mb-3 text-base font-medium">{saved ? 'Edit policy draft' : 'New policy draft'}</h2>
      {!saved && <p className="mb-3 text-sm text-[#A8A8AB]">Starts from the active policy (version {version}).</p>}
      <StateLine loading={live.isLoading} error={live.error} emptyText="" />
      {isConflict(save.error) && (
        <div role="alert" className="mb-3 rounded-[6px] border border-[#EF4444]/40 p-2 text-sm">
          Someone else changed this draft or the active policy. Nothing was saved. Close the editor,
          reload the drafts and re-apply your edit. ({errorText(save.error)})
        </div>
      )}
      <fieldset disabled={!open} className="m-0 min-w-0 space-y-3 border-0 p-0">
        {current.map((r, i) => (
          <RuleEditor key={i} rule={r} agents={agents} onChange={(n) => edit(i, n)}
            onRemove={() => setRules(current.filter((_, j) => j !== i))} />
        ))}
        {!current.length && !live.isLoading && <p className="text-sm text-[#A8A8AB]">This draft has no rules.</p>}
        <Button size="sm" variant="secondary" disabled={!open || current.length >= 100}
          onClick={() => setRules([...current, newRule(current.length + 1)])}>
          Add rule
        </Button>
        <div className="flex flex-wrap gap-3">
          <Field name="Reason (at least 5 characters)">
            <input className={inputClass} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <Field name="Reviewers (comma separated)">
            <input className={inputClass} value={reviewers} onChange={(e) => setReviewers(e.target.value)} />
          </Field>
        </div>
      </fieldset>
      {saved && (
        <div className="mt-4 space-y-3">
          <section aria-label="Exact diff against the active policy">
            <h3 className="mb-1 text-sm font-medium">Exact diff against the active policy</h3>
            <RuleDiff diff={saved.diff} />
          </section>
          <Findings items={saved.findings} title="Lint findings" />
          <p className="text-xs text-[#A8A8AB]">Diff and findings refresh each time you save.</p>
        </div>
      )}
      {save.error && !isConflict(save.error) && (
        <p role="alert" className="mt-2 text-sm text-[#EF4444]">{errorText(save.error)}</p>
      )}
      {discard.error && <p role="alert" className="mt-2 text-sm text-[#EF4444]">{errorText(discard.error)}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        {open && (
          <Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>
            Save draft
          </Button>
        )}
        {saved && open && (
          <>
            <Button variant="danger" onClick={() => setPublishing(true)}>Review and publish…</Button>
            <Button variant="secondary" loading={discard.isPending} onClick={() => discard.mutate()}>Discard draft</Button>
          </>
        )}
        <Button variant="ghost" onClick={onDone}>Close</Button>
      </div>
      {publishing && saved && canEdit && (
        <PublishDialog draft={saved} agents={agents} version={version} onClose={() => setPublishing(false)} />
      )}
    </Card>
  );
}

export function PolicyDrafts({ agents }: { agents: AgentRow[] }) {
  const canEdit = useCanEdit();
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<Draft | 'new' | null>(null);
  const drafts = useQuery({
    queryKey: ['gov', 'drafts', offset],
    queryFn: () => apiClient.get<{ items: Draft[] }>(`${BASE}/drafts`, { limit: PAGE, offset }),
  });
  const policy = useQuery({
    queryKey: ['gov', 'policy'],
    queryFn: () => apiClient.get<{ version: number; rules: Rule[] }>(`${BASE}/policy`),
  });
  const version = policy.data?.version ?? 0;
  if (editing) {
    return (
      <Editor key={editing === 'new' ? 'new' : editing.id} draft={editing === 'new' ? null : editing}
        agents={agents} version={version} onDone={() => setEditing(null)} />
    );
  }
  const items = drafts.data?.items ?? [];
  return (
    <Card>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-medium">Policy drafts <span className="text-sm font-normal text-[#A8A8AB]">(active version {version})</span></h2>
        {canEdit && <Button size="sm" onClick={() => setEditing('new')}>New draft from active policy</Button>}
      </div>
      <StateLine loading={drafts.isLoading} error={drafts.error} empty={!!drafts.data && !items.length}
        emptyText="No policy drafts yet." />
      {!!items.length && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <caption className="sr-only">Policy drafts</caption>
            <thead>
              <tr className="text-left text-[#A8A8AB]">
                <th scope="col" className="py-1">Reason</th><th scope="col">Owner</th>
                <th scope="col">Base version</th><th scope="col">Status</th>
                <th scope="col">Created</th><th scope="col"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((d) => (
                <tr key={d.id} className="border-t border-white/[0.06] align-top">
                  <td className="py-2">{d.reason}</td>
                  <td>{d.created_by}</td>
                  <td>{d.base_version}</td>
                  <td>
                    <Badge variant={d.status === 'draft' ? 'info' : 'neutral'}>{STATUS_TEXT[d.status] ?? d.status}</Badge>{' '}
                    {d.stale && <Badge variant="warning">STALE</Badge>}
                  </td>
                  <td className="text-[#A8A8AB]">{d.created_at?.slice(0, 16)} by {d.created_by}</td>
                  <td>
                    <Button size="xs" variant="secondary" aria-label={`Open draft: ${d.reason}`} onClick={() => setEditing(d)}>
                      {canEdit && d.status === 'draft' ? 'Edit' : 'View'}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Pager offset={offset} count={items.length} onChange={setOffset} />
    </Card>
  );
}
