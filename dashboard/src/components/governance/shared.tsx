import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { Badge, type BadgeVariant } from '@/components/common/Badge';
import { Button } from '@/components/common/Button';
import { Modal } from '@/components/common/Modal';
import { useAuth } from '@/contexts/AuthContext';

export const BASE = '/api/v1/governance';
export const PAGE = 20;

export interface Rule {
  name: string;
  effect: 'allow' | 'deny';
  priority: number;
  description?: string | null;
  conditions: Record<string, unknown>;
}
export interface Finding { code: string; severity: string; detail: string }
export interface RuleChange { name: string; fields: string[]; before: Rule; after: Rule }
export interface RuleDiffData { added: Rule[]; removed: Rule[]; changed: RuleChange[] }
export interface CapChange {
  capability_id: string; name: string; risk: string; before: string; after: string; code: string;
}
export interface CapDiffData {
  changes: CapChange[];
  excluded: { capability_id: string; name: string; label: string }[];
  blocked?: { capability_id: string; code: string }[];
}
export interface Affects { all_agents: boolean; agent_ids: string[]; capability_ids: string[] }
export interface AgentRow { id: string; name: string; role: string }

export type Permission = 'loading' | 'write' | 'read' | 'unknown';

/**
 * What the server says the caller may do (`GET /governance/me`, the same predicate as the write
 * guard). The signed-in identity only keys the cache and switches the query on: it never decides
 * anything. Only an explicit `can_write: true` gives `write`. Loading, an error, a failed refetch
 * and a signed-out browser never do, so write controls stay off until the server says yes.
 */
export function usePermission(): Permission {
  const { status, me } = useAuth();
  const q = useQuery({
    queryKey: ['gov', 'me', me?.company_id ?? null, me?.user?.id ?? null],
    enabled: status === 'authenticated',
    queryFn: () => apiClient.get<{ can_write: boolean }>(`${BASE}/me`),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: true,
    retry: false,
  });
  if (status === 'loading' || (status === 'authenticated' && q.isPending)) return 'loading';
  if (status !== 'authenticated' || q.status === 'error') return 'unknown';
  return q.data?.can_write === true ? 'write' : 'read';
}

export const useCanEdit = () => usePermission() === 'write';

export const label = (s: string) => s.replace(/_/g, ' ');
export const errorText = (e: unknown) => (e instanceof Error ? e.message : 'Request failed');
/** The HTTP status of a failed request. Matches by shape so a mocked client works too. */
export const httpStatus = (e: unknown): number | undefined =>
  typeof e === 'object' && e !== null && 'status' in e ? Number((e as { status: unknown }).status) : undefined;
export const isConflict = (e: unknown) => httpStatus(e) === 409;

export const inputClass =
  'w-full rounded-[6px] bg-[#141416] border border-white/[0.12] px-3 py-2 text-sm';

export function Field({ name, children, hint }: { name: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex min-w-[12rem] flex-1 flex-col gap-1 text-sm">
      <span className="text-[#A8A8AB]">{name}</span>
      {children}
      {hint && <span className="text-xs text-[#A8A8AB]">{hint}</span>}
    </label>
  );
}

const SEVERITY: Record<string, BadgeVariant> = { high: 'danger', medium: 'warning', low: 'info' };

export function Findings({ items, title = 'Risk findings' }: { items: Finding[]; title?: string }) {
  if (!items.length) return <p className="text-sm text-[#A8A8AB]">{title}: none.</p>;
  return (
    <section aria-label={title}>
      <h3 className="mb-1 text-sm font-medium">{title} (advisory)</h3>
      <ul className="space-y-1">
        {items.map((f, i) => (
          <li key={`${f.code}-${i}`} className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant={SEVERITY[f.severity] ?? 'neutral'}>{f.severity.toUpperCase()}</Badge>
            <code>{f.code}</code>
            <span className="text-[#A8A8AB]">{f.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

const DECISION_VARIANT: Record<string, BadgeVariant> = { allow: 'success', deny: 'danger' };

export function DecisionBadge({ value }: { value: string }) {
  const mark = value === 'allow' ? '✓ ' : value === 'deny' ? '✕ ' : '';
  return <Badge variant={DECISION_VARIANT[value] ?? 'neutral'}>{mark}{value.toUpperCase()}</Badge>;
}

function condText(c: Record<string, unknown>): string {
  const parts = Object.entries(c)
    .filter(([k]) => k !== 'governance')
    .map(([k, v]) => `${label(k)}: ${Array.isArray(v) ? v.join(', ') : JSON.stringify(v)}`);
  return parts.join(' · ') || 'everything';
}

function RuleLine({ rule, mark }: { rule: Rule; mark: string }) {
  return (
    <li className="text-sm">
      <span aria-hidden="true" className="mr-1 font-mono">{mark}</span>
      <strong>{rule.effect}</strong> {rule.name} <span className="text-[#A8A8AB]">
        (priority {rule.priority}; {condText(rule.conditions)})</span>
    </li>
  );
}

export function RuleDiff({ diff }: { diff: RuleDiffData }) {
  const empty = !diff.added.length && !diff.removed.length && !diff.changed.length;
  if (empty) return <p className="text-sm text-[#A8A8AB]">No rule changes.</p>;
  return (
    <ul aria-label="Rule changes" className="space-y-1">
      {diff.added.map((r) => <RuleLine key={`a-${r.name}`} rule={r} mark="+ added" />)}
      {diff.removed.map((r) => <RuleLine key={`r-${r.name}`} rule={r} mark="- removed" />)}
      {diff.changed.map((c) => (
        <li key={`c-${c.name}`} className="text-sm">
          <span aria-hidden="true" className="mr-1 font-mono">~ changed</span>
          {c.name} <span className="text-[#A8A8AB]">({c.fields.join(', ')}): </span>
          {c.before.effect}/{c.before.priority} → {c.after.effect}/{c.after.priority}
          <div className="ml-4 text-xs text-[#A8A8AB]">
            before: {condText(c.before.conditions)}<br />after: {condText(c.after.conditions)}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function CapabilityDiff({ diff }: { diff: CapDiffData }) {
  return (
    <div className="space-y-2">
      {diff.changes.length ? (
        <table className="w-full text-sm">
          <caption className="sr-only">Capability changes</caption>
          <thead>
            <tr className="text-left text-[#A8A8AB]">
              <th scope="col" className="py-1">Capability</th><th scope="col">Before</th>
              <th scope="col">After</th><th scope="col">Code</th>
            </tr>
          </thead>
          <tbody>
            {diff.changes.map((c) => (
              <tr key={c.capability_id} className="border-t border-white/[0.06]">
                <td className="py-1">{c.name}</td>
                <td><DecisionBadge value={c.before} /></td>
                <td><DecisionBadge value={c.after} /></td>
                <td className="text-[#A8A8AB]">{c.code}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-[#A8A8AB]">No capability decision changes.</p>
      )}
      {!!diff.blocked?.length && (
        <p role="note" className="text-sm">
          Still blocked by an existing rule: {diff.blocked.map((b) => `${b.capability_id} (${b.code})`).join(', ')}
        </p>
      )}
      {!!diff.excluded.length && (
        <details className="text-sm">
          <summary className="cursor-pointer">Not changed by policy ({diff.excluded.length})</summary>
          <ul className="mt-1 space-y-0.5 text-[#A8A8AB]">
            {diff.excluded.map((e) => <li key={e.capability_id}>{e.name}: {e.label}</li>)}
          </ul>
        </details>
      )}
    </div>
  );
}

export function Pager({
  offset, count, onChange,
}: { offset: number; count: number; onChange: (next: number) => void }) {
  return (
    <nav aria-label="Pagination" className="mt-3 flex items-center gap-2 text-sm">
      <Button size="xs" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - PAGE))}>
        Previous
      </Button>
      <span aria-live="polite">Showing {count ? offset + 1 : 0}–{offset + count}</span>
      <Button size="xs" variant="secondary" disabled={count < PAGE} onClick={() => onChange(offset + PAGE)}>
        Next
      </Button>
    </nav>
  );
}

export function ConfirmModal({
  open, title, onClose, onConfirm, confirmLabel, pending, error, disabled, danger = false, children,
}: {
  open: boolean; title: string; onClose: () => void; onConfirm: () => void; confirmLabel: string;
  pending?: boolean; error?: ReactNode; disabled?: boolean; danger?: boolean; children: ReactNode;
}) {
  return (
    <Modal isOpen={open} onClose={onClose} title={title} size="lg">
      <div className="space-y-3">
        {children}
        {error && <div role="alert" className="text-sm text-[#EF4444]">{error}</div>}
        <div className="flex gap-2">
          <Button variant={danger ? 'danger-solid' : 'primary'} disabled={disabled} loading={pending} onClick={onConfirm}>
            {confirmLabel}
          </Button>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
        </div>
      </div>
    </Modal>
  );
}

export function StateLine({
  loading, error, empty, emptyText,
}: { loading?: boolean; error?: unknown; empty?: boolean; emptyText: string }) {
  if (loading) return <p role="status" className="text-sm text-[#A8A8AB]">Loading…</p>;
  if (error) return <p role="alert" className="text-sm text-[#EF4444]">{errorText(error)}</p>;
  if (empty) return <p className="text-sm text-[#A8A8AB]">{emptyText}</p>;
  return null;
}
