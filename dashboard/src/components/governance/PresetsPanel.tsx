import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Card } from '@/components/common/Card';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import {
  BASE, CapabilityDiff, ConfirmModal, Field, RuleDiff, StateLine, errorText, inputClass, useCanEdit,
  type AgentRow, type CapDiffData, type Rule,
} from './shared';

interface PresetItem { key: string; label: string; summary: string; unavailable_reason: string | null }
interface Preview {
  preset: string; base_version: number; applied: boolean; rules: Rule[];
  capability_diff: CapDiffData; draft: { id: string } | null;
}

function PresetDialog({ agent, preset, onClose }: { agent: AgentRow; preset: PresetItem; onClose: () => void }) {
  const qc = useQueryClient();
  const [reason, setReason] = useState('');
  const [made, setMade] = useState(false);
  const preview = useQuery({
    queryKey: ['gov', 'preset', agent.id, preset.key],
    queryFn: () => apiClient.get<Preview>(`${BASE}/agents/${agent.id}/autonomy-presets/${preset.key}`),
  });
  const create = useMutation({
    mutationFn: () =>
      apiClient.post<Preview>(`${BASE}/agents/${agent.id}/autonomy-presets/${preset.key}/draft`, {
        reason: reason.trim(),
      }),
    onSuccess: () => { setMade(true); qc.invalidateQueries({ queryKey: ['gov', 'drafts'] }); },
  });
  if (made) {
    return (
      <ConfirmModal open title={`${preset.label} for ${agent.name}`} onClose={onClose} onConfirm={onClose} confirmLabel="Done">
        <p role="status" className="text-sm">
          Policy draft created. Nothing is active yet: review and publish it under Policy.
        </p>
      </ConfirmModal>
    );
  }
  const p = preview.data;
  return (
    <ConfirmModal open title={`${preset.label} for ${agent.name}`} onClose={onClose} confirmLabel="Create policy draft"
      pending={create.isPending} disabled={!p || reason.trim().length < 5} onConfirm={() => create.mutate()}
      error={create.error && errorText(create.error)}>
      <p className="text-sm">{preset.summary}</p>
      <p role="note" className="text-sm">
        This only creates a policy draft. It changes nothing until a human administrator publishes it,
        and it never bypasses role, designation or an existing explicit deny.
      </p>
      <StateLine loading={preview.isLoading} error={preview.error} emptyText="" />
      {p && (
        <>
          <section aria-label="Capability changes"><h3 className="mb-1 text-sm font-medium">Exact capability changes</h3><CapabilityDiff diff={p.capability_diff} /></section>
          <details className="text-sm">
            <summary className="cursor-pointer">Rules this draft adds ({p.rules.length})</summary>
            <RuleDiff diff={{ added: p.rules, removed: [], changed: [] }} />
          </details>
        </>
      )}
      <Field name="Reason (at least 5 characters)">
        <input className={inputClass} value={reason} maxLength={400} onChange={(e) => setReason(e.target.value)} />
      </Field>
    </ConfirmModal>
  );
}

export function PresetsPanel({ agents, defaultAgentId }: { agents: AgentRow[]; defaultAgentId: string }) {
  const canEdit = useCanEdit();
  const [agentId, setAgentId] = useState('');
  const [picked, setPicked] = useState<PresetItem | null>(null);
  const agent = agents.find((a) => a.id === (agentId || defaultAgentId));
  const presets = useQuery({
    queryKey: ['gov', 'presets', agent?.id],
    enabled: !!agent,
    queryFn: () => apiClient.get<{ items: PresetItem[] }>(`${BASE}/agents/${agent?.id}/autonomy-presets`),
  });
  const items = presets.data?.items ?? [];
  return (
    <Card>
      <p className="mb-3 text-sm text-[#A8A8AB]">
        An autonomy preset is a named shape of access. Choosing one creates a policy draft with an
        exact capability diff. It is never published immediately.
        {!canEdit && ' Only a human administrator can create one.'}
      </p>
      <div className="mb-3 flex">
        <Field name="Agent">
          <select className={inputClass} value={agent?.id ?? ''} onChange={(e) => setAgentId(e.target.value)}>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
      </div>
      <StateLine loading={presets.isLoading} error={presets.error} empty={!!presets.data && !items.length}
        emptyText="No presets." />
      <ul className="space-y-2">
        {items.map((p) => (
          <li key={p.key} className="flex flex-wrap items-center justify-between gap-2 border-t border-white/[0.06] py-2 text-sm">
            <div>
              <div className="font-medium">{p.label}</div>
              <div className="text-[#A8A8AB]">{p.summary}</div>
              {p.unavailable_reason && <Badge variant="neutral">Unavailable: {p.unavailable_reason}</Badge>}
            </div>
            {canEdit && (
              <Button size="xs" variant="secondary" disabled={!!p.unavailable_reason}
                aria-label={`Preview ${p.label}`} onClick={() => setPicked(p)}>
                Preview and draft…
              </Button>
            )}
          </li>
        ))}
      </ul>
      {picked && agent && <PresetDialog agent={agent} preset={picked} onClose={() => setPicked(null)} />}
    </Card>
  );
}
