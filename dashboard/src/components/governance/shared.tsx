import { useState, type ReactNode } from 'react';
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
export interface Finding { code: string; severity: string; detail: string; capabilities?: string[] }
export interface RuleChange { name: string; fields: string[]; before: Rule; after: Rule }
export interface RuleDiffData { added: Rule[]; removed: Rule[]; changed: RuleChange[] }
export interface CapChange {
  capability_id: string; name: string; display_name?: string; risk: string; before: string;
  after: string; code: string;
}
export interface CapDiffData {
  changes: CapChange[];
  excluded: { capability_id: string; name: string; display_name?: string; label: string }[];
  blocked?: { capability_id: string; code: string }[];
}
export interface Affects { all_agents: boolean; agent_ids: string[]; capability_ids: string[] }
export interface AgentRow { id: string; name: string; role: string }

/** What the server's catalogue says about one capability. The id is the only key; text is display. */
export interface CapMeta {
  id: string;
  name?: string;
  display_name: string;
  description: string;
  category?: string;
  risk?: string;
  support?: string;
  tool_name?: string | null;
  limitations?: string | null;
  examples?: string[];
  explicit_allow_required?: boolean;
  scope_schema?: { conditions?: string[] };
}

export const UNAVAILABLE = 'Description unavailable';
const upper = (w: string) => w.charAt(0).toUpperCase() + w.slice(1);
/** Fallback for an id the catalogue does not list: a readable name and no invented description. */
export const capFallback = (id: string): CapMeta => ({
  id,
  display_name: id.slice(id.indexOf('.') + 1).split(/[-_\s]+/).filter(Boolean).map(upper).join(' ') || id,
  description: UNAVAILABLE,
});
export const firstSentence = (text: string | undefined) =>
  (text ?? UNAVAILABLE).match(/^.*?[.!?](?=\s|$)/)?.[0] ?? text ?? UNAVAILABLE;
/** Fill in text an older or partial response lacks, so a row never shows a blank name. */
export const withMeta = <T extends { id: string; name?: string; display_name?: string; description?: string }>(c: T) =>
  ({ ...c, display_name: c.display_name ?? (c.name && c.name !== c.id ? c.name : capFallback(c.id).display_name),
     description: c.description ?? UNAVAILABLE });

/**
 * The server's capability catalogue (`GET /governance/catalog`), looked up by technical id or by
 * tool name (what rules and grants store). Nothing here decides access: it only turns an id into
 * text. An id the catalogue lacks falls back to a readable name, never an invented description.
 */
export function useCatalog() {
  const q = useQuery({
    queryKey: ['gov', 'catalog'],
    queryFn: () => apiClient.get<{ capabilities?: CapMeta[] }>(`${BASE}/catalog`),
  });
  const caps = (q.data?.capabilities ?? []).map(withMeta);
  const byId = new Map(caps.map((c) => [c.id, c]));
  const byTool = new Map(caps.filter((c) => c.tool_name).map((c) => [c.tool_name as string, c]));
  return {
    caps, isLoading: q.isLoading, error: q.error,
    byId: (id: string) => byId.get(id) ?? capFallback(id),
    byTool: (tool: string): CapMeta | undefined => byTool.get(tool),
  };
}

export function CopyId({ id }: { id: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button size="xs" variant="ghost" aria-label={`Copy technical ID ${id}`}
      onClick={() => {
        try { void navigator.clipboard?.writeText(id); setDone(true); } catch { setDone(false); }
      }}>
      {done ? 'Copied' : 'Copy ID'}
    </Button>
  );
}

/** Name first, then the effect, then the technical id in muted monospace. Wraps, never scrolls. */
export function CapName({ cap, describe = true }: { cap: CapMeta; describe?: boolean }) {
  return (
    <span className="block min-w-0 break-words [overflow-wrap:anywhere]">
      <span className="font-medium">{cap.display_name}</span>
      {describe && (
        <span className="block text-xs text-[#A8A8AB]">{firstSentence(cap.description)}</span>
      )}
      <code className="block font-mono text-[11px] text-[#8A8A8E]">{cap.id}</code>
    </span>
  );
}

/** A tool name as a rule or grant stores it, shown as its capability name plus the stored value. */
export function useToolText() {
  const { byTool } = useCatalog();
  return (tool: string) => {
    const c = byTool(tool);
    return c ? `${c.display_name} (${tool})` : tool;
  };
}

/** The capabilities a change touches, named, behind a disclosure so a long list stays short. */
export function AffectedCapabilities({ ids }: { ids: string[] }) {
  const { byId } = useCatalog();
  if (!ids.length) return null;
  return (
    <details className="text-sm">
      <summary className="cursor-pointer">Show the {ids.length} capabilit{ids.length === 1 ? 'y' : 'ies'}</summary>
      <ul className="mt-1 space-y-1 break-words">
        {ids.map((id) => <li key={id}><CapName cap={byId(id)} describe={false} /></li>)}
      </ul>
    </details>
  );
}

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
  const { byId } = useCatalog();
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
            {!!f.capabilities?.length && (
              <span className="basis-full pl-2 text-xs text-[#A8A8AB]">
                Capabilities involved: {f.capabilities.map((id) => `${byId(id).display_name} (${id})`).join(', ')}
              </span>
            )}
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

function useCondText() {
  const tool = useToolText();
  return (c: Record<string, unknown>): string => {
    const parts = Object.entries(c)
      .filter(([k]) => k !== 'governance')
      .map(([k, v]) => {
        const list = Array.isArray(v) ? v.map(String) : null;
        const text = k === 'tool_name' && list ? list.map(tool).join(', ') : list ? list.join(', ') : JSON.stringify(v);
        return `${k === 'tool_name' ? 'capability' : label(k)}: ${text}`;
      });
    return parts.join(' · ') || 'everything';
  };
}

function RuleLine({ rule, mark }: { rule: Rule; mark: string }) {
  const condText = useCondText();
  return (
    <li className="text-sm">
      <span aria-hidden="true" className="mr-1 font-mono">{mark}</span>
      <strong>{rule.effect}</strong> {rule.name} <span className="text-[#A8A8AB]">
        (priority {rule.priority}; {condText(rule.conditions)})</span>
    </li>
  );
}

export function RuleDiff({ diff }: { diff: RuleDiffData }) {
  const condText = useCondText();
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
  const { byId } = useCatalog();
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
                <td className="py-1">
                  <CapName cap={{ ...byId(c.capability_id), display_name: c.display_name ?? c.name }} describe={false} />
                </td>
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
          Still blocked by an existing rule: {diff.blocked.map((b) => `${byId(b.capability_id).display_name} (${b.capability_id}, ${b.code})`).join(', ')}
        </p>
      )}
      {!!diff.excluded.length && (
        <details className="text-sm">
          <summary className="cursor-pointer">Not changed by policy ({diff.excluded.length})</summary>
          <ul className="mt-1 space-y-0.5 text-[#A8A8AB]">
            {diff.excluded.map((e) => <li key={e.capability_id}>{e.display_name ?? e.name} ({e.capability_id}): {e.label}</li>)}
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
