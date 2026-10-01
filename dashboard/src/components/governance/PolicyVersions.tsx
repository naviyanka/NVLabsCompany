import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import {
  BASE, PAGE, ConfirmModal, Field, Findings, Pager, RuleDiff, StateLine, errorText, inputClass,
  isConflict, useCanEdit, type Affects, type Finding, type RuleDiffData,
} from './shared';

interface VersionRow {
  version: number; status: string; base_version: number | null; published_by: string;
  reason: string | null; rollback_of: number | null; rule_count: number; created_at: string | null;
}
interface VersionDetail extends VersionRow { diff_from_previous: RuleDiffData; affects: Affects }
interface Preview {
  target_version: number; current_version: number; diff: RuleDiffData; affects: Affects;
  loosens: boolean; applies_at_once: boolean; findings: Finding[];
}

const scope = (a: Affects) =>
  `${a.all_agents ? 'every agent' : `${a.agent_ids.length} agent(s)`}, ${a.capability_ids.length} capabilit${a.capability_ids.length === 1 ? 'y' : 'ies'}`;

function RollbackDialog({ number, onClose }: { number: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const preview = useQuery({
    queryKey: ['gov', 'rollback-preview', number],
    queryFn: () => apiClient.get<Preview>(`${BASE}/versions/${number}/rollback-preview`),
  });
  const run = useMutation({
    mutationFn: () =>
      apiClient.post<{ applied: boolean; version?: number }>(`${BASE}/versions/${number}/rollback`, {
        reason: reason.trim(), expected_version: preview.data?.current_version,
      }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['gov'] });
      setOutcome(r.applied ? `Rollback applied as new version ${r.version}. History is kept.`
        : 'This rollback loosens access, so it became a draft. Publish it from Drafts.');
    },
  });
  const p = preview.data;
  if (outcome) {
    return (
      <ConfirmModal open title={`Roll back to version ${number}`} onClose={onClose} onConfirm={onClose} confirmLabel="Done">
        <p role="status" className="text-sm">{outcome}</p>
      </ConfirmModal>
    );
  }
  return (
    <ConfirmModal open title={`Roll back to version ${number}`} onClose={onClose} danger confirmLabel="Roll back"
      pending={run.isPending} disabled={!p || !reviewed || reason.trim().length < 5 || isConflict(run.error)}
      onConfirm={() => run.mutate()}
      error={run.error && (
        <>{isConflict(run.error) ? 'The active policy changed since this preview. Close this and open it again. ' : ''}{errorText(run.error)}</>
      )}>
      <StateLine loading={preview.isLoading} error={preview.error} emptyText="" />
      {p && (
        <>
          <p className="text-sm">
            Rolling back never deletes history. It makes version {p.current_version + 1} hold the
            rules of version {p.target_version}.{' '}
            {p.applies_at_once
              ? 'This change only tightens access, so it applies at once.'
              : <><Badge variant="warning">LOOSENS ACCESS</Badge> It becomes a draft that another person must publish.</>}
          </p>
          <section aria-label="Exact rule changes"><h3 className="mb-1 text-sm font-medium">Exact rule changes</h3><RuleDiff diff={p.diff} /></section>
          <p className="text-sm">Affects {scope(p.affects)}.</p>
          <Findings items={p.findings} title="Risk findings in the target version" />
        </>
      )}
      <Field name="Reason (at least 5 characters)">
        <input className={inputClass} value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} />
        I have reviewed the exact changes.
      </label>
    </ConfirmModal>
  );
}

function Detail({ number, onClose, onRollback }: { number: number; onClose: () => void; onRollback: () => void }) {
  const canEdit = useCanEdit();
  const detail = useQuery({
    queryKey: ['gov', 'version', number],
    queryFn: () => apiClient.get<VersionDetail>(`${BASE}/versions/${number}`),
  });
  const d = detail.data;
  return (
    <Card>
      <h2 className="mb-2 text-base font-medium">Version {number}</h2>
      <StateLine loading={detail.isLoading} error={detail.error} emptyText="" />
      {d && (
        <div className="space-y-3">
          <p className="text-sm">
            {d.status}, published by {d.published_by}{d.reason ? `: ${d.reason}` : ''}
            {d.rollback_of ? ` (rollback of version ${d.rollback_of})` : ''}
          </p>
          <section aria-label="Changes from the previous version">
            <h3 className="mb-1 text-sm font-medium">Changes from the previous version</h3>
            <RuleDiff diff={d.diff_from_previous} />
          </section>
          <p className="text-sm">Affected: {scope(d.affects)}.</p>
        </div>
      )}
      <div className="mt-3 flex gap-2">
        {canEdit && (
          <Button variant="danger" disabled={!d || d.status === 'active'} onClick={onRollback}>
            {d?.status === 'active' ? 'This is the active version' : 'Roll back to this version…'}
          </Button>
        )}
        <Button variant="ghost" onClick={onClose}>Close</Button>
      </div>
    </Card>
  );
}

export function PolicyVersions() {
  const [offset, setOffset] = useState(0);
  const [open, setOpen] = useState<number | null>(null);
  const [rolling, setRolling] = useState<number | null>(null);
  const versions = useQuery({
    queryKey: ['gov', 'versions', offset],
    queryFn: () => apiClient.get<{ items: VersionRow[] }>(`${BASE}/versions`, { limit: PAGE, offset }),
  });
  const items = versions.data?.items ?? [];
  return (
    <div className="space-y-4">
      {open !== null && <Detail number={open} onClose={() => setOpen(null)} onRollback={() => setRolling(open)} />}
      <Card>
        <h2 className="mb-3 text-base font-medium">Policy versions</h2>
        <StateLine loading={versions.isLoading} error={versions.error} empty={!!versions.data && !items.length}
          emptyText="No policy has been published yet." />
        {!!items.length && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <caption className="sr-only">Policy versions</caption>
              <thead>
                <tr className="text-left text-[#A8A8AB]">
                  <th scope="col" className="py-1">Version</th><th scope="col">Status</th>
                  <th scope="col">Rules</th><th scope="col">Published by</th>
                  <th scope="col">Reason</th><th scope="col">When</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {items.map((v) => (
                  <tr key={v.version} className="border-t border-white/[0.06] align-top">
                    <td className="py-2">{v.version}</td>
                    <td><Badge variant={v.status === 'active' ? 'success' : 'neutral'}>{v.status}</Badge></td>
                    <td>{v.rule_count}</td>
                    <td>{v.published_by}</td>
                    <td className="text-[#A8A8AB]">{v.reason}{v.rollback_of ? ` (rollback of ${v.rollback_of})` : ''}</td>
                    <td className="text-[#A8A8AB]">{v.created_at?.slice(0, 16)}</td>
                    <td>
                      <Button size="xs" variant="secondary" aria-label={`View version ${v.version}`} onClick={() => setOpen(v.version)}>
                        View
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
      {rolling !== null && <RollbackDialog number={rolling} onClose={() => setRolling(null)} />}
    </div>
  );
}
