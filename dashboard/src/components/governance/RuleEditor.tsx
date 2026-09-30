import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/common/Button';
import { Badge } from '@/components/common/Badge';
import { apiClient } from '@/api/client';
import { BASE, Field, inputClass, type AgentRow, type Rule } from './shared';

interface Capability {
  id: string; name: string; tool_name: string | null; support: string; risk: string;
  explicit_allow_required: boolean;
}

interface Option { value: string; text: string; disabled?: boolean; note?: string }

function CheckList({
  legend, options, selected, onChange, empty,
}: {
  legend: string; options: Option[]; selected: string[]; onChange: (next: string[]) => void; empty: string;
}) {
  // A value the rule already holds stays visible even when it is not a catalogue name (a pattern).
  const known = new Set(options.map((o) => o.value));
  const all: Option[] = [...options, ...selected.filter((s) => !known.has(s)).map((s) => ({ value: s, text: s }))];
  const toggle = (v: string) =>
    onChange(selected.includes(v) ? selected.filter((s) => s !== v) : [...selected, v]);
  return (
    <fieldset className="min-w-[14rem] flex-1 text-sm">
      <legend className="text-[#A8A8AB]">{legend}{selected.length ? ` (${selected.length})` : ` (${empty})`}</legend>
      <div className="mt-1 max-h-40 space-y-0.5 overflow-y-auto rounded-[6px] border border-white/[0.08] p-2">
        {all.map((o) => (
          <label key={o.value} className="flex items-center gap-2">
            <input type="checkbox" checked={selected.includes(o.value)} disabled={o.disabled}
              onChange={() => toggle(o.value)} />
            <span>{o.text}</span>
            {o.note && <Badge variant="neutral">{o.note}</Badge>}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

const asList = (v: unknown): string[] => (Array.isArray(v) ? (v as string[]) : typeof v === 'string' ? [v] : []);

function setCond(rule: Rule, key: string, value: unknown): Rule {
  const conditions = { ...rule.conditions };
  const empty = value === undefined || (Array.isArray(value) && !value.length) || value === '';
  if (empty) delete conditions[key];
  else conditions[key] = value;
  return { ...rule, conditions };
}

function setMeta(rule: Rule, key: 'owner' | 'review_by', value: string): Rule {
  const meta = { ...((rule.conditions.governance as Record<string, string>) ?? {}) };
  if (value) meta[key] = value;
  else delete meta[key];
  return setCond(rule, 'governance', Object.keys(meta).length ? meta : undefined);
}

export function RuleEditor({
  rule, agents, onChange, onRemove,
}: { rule: Rule; agents: AgentRow[]; onChange: (r: Rule) => void; onRemove: () => void }) {
  const catalog = useQuery({
    queryKey: ['gov', 'catalog'],
    queryFn: () => apiClient.get<{ capabilities: Capability[] }>(`${BASE}/catalog`),
  });
  const tools: Option[] = (catalog.data?.capabilities ?? [])
    .filter((c) => c.tool_name)
    .map((c) => ({
      value: c.tool_name as string,
      text: c.name,
      disabled: c.support === 'unsupported',
      note: c.support === 'unsupported' ? 'Not enforceable' : c.explicit_allow_required ? 'explicit allow only' : undefined,
    }));
  const meta = (rule.conditions.governance as Record<string, string> | undefined) ?? {};
  const window = (rule.conditions.time_of_day as { start?: number; end?: number } | undefined) ?? {};
  const setHour = (k: 'start' | 'end', v: string) => {
    const next = { ...window };
    if (v === '') delete next[k];
    else next[k] = Number(v);
    onChange(setCond(rule, 'time_of_day', Object.keys(next).length ? next : undefined));
  };
  const n = rule.name || 'new rule';
  return (
    <fieldset className="space-y-3 rounded-[8px] border border-white/[0.1] p-3">
      <legend className="px-1 text-sm font-medium">Rule: {n}</legend>
      <div className="flex flex-wrap gap-3">
        <Field name="Rule name">
          <input className={inputClass} value={rule.name} maxLength={255}
            onChange={(e) => onChange({ ...rule, name: e.target.value })} />
        </Field>
        <Field name="Effect">
          <select className={inputClass} value={rule.effect}
            onChange={(e) => onChange({ ...rule, effect: e.target.value as Rule['effect'] })}>
            <option value="allow">Allow</option>
            <option value="deny">Deny</option>
          </select>
        </Field>
        <Field name="Priority" hint="Lower numbers are checked first.">
          <input type="number" min={0} max={100000} className={inputClass} value={rule.priority}
            onChange={(e) => onChange({ ...rule, priority: Number(e.target.value) })} />
        </Field>
      </div>
      <div className="flex flex-wrap gap-3">
        <CheckList legend="Capabilities" options={tools} empty="every tool"
          selected={asList(rule.conditions.tool_name)}
          onChange={(v) => onChange(setCond(rule, 'tool_name', v))} />
        <CheckList legend="Agents" empty="every agent"
          options={agents.map((a) => ({ value: a.id, text: a.name }))}
          selected={asList(rule.conditions.agent_id)}
          onChange={(v) => onChange(setCond(rule, 'agent_id', v))} />
        <CheckList legend="Risk levels" empty="any risk"
          options={['read', 'write'].map((r) => ({ value: r, text: r }))}
          selected={asList(rule.conditions.risk_level)}
          onChange={(v) => onChange(setCond(rule, 'risk_level', v))} />
      </div>
      <div className="flex flex-wrap gap-3">
        <Field name="Active from hour (0-24)">
          <input type="number" min={0} max={24} className={inputClass} value={window.start ?? ''}
            onChange={(e) => setHour('start', e.target.value)} />
        </Field>
        <Field name="Active until hour (0-24)">
          <input type="number" min={0} max={24} className={inputClass} value={window.end ?? ''}
            onChange={(e) => setHour('end', e.target.value)} />
        </Field>
        <Field name="Owner">
          <input className={inputClass} value={meta.owner ?? ''} maxLength={255}
            onChange={(e) => onChange(setMeta(rule, 'owner', e.target.value))} />
        </Field>
        <Field name="Review by">
          <input type="date" className={inputClass} value={meta.review_by ?? ''}
            onChange={(e) => onChange(setMeta(rule, 'review_by', e.target.value))} />
        </Field>
      </div>
      <p className="text-xs text-[#A8A8AB]">
        Resource scope: the engine matches by tool, agent, risk level and hour. Approval is set by the
        agent's autonomy level and by explicit-allow tools, not by a rule.
      </p>
      <Button size="xs" variant="danger" onClick={onRemove}>Remove rule {n}</Button>
    </fieldset>
  );
}

export const newRule = (n: number): Rule => ({
  name: `rule-${n}`, effect: 'deny', priority: 100, conditions: {},
});
