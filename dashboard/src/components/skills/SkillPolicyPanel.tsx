/**
 * SkillPolicyPanel — edit the company skill access policy.
 *
 * Wraps GET/PUT /api/v1/companies/{id}/skill-policy. The document is:
 *   { schemaVersion, revision, defaultEffect: 'allow'|'deny', rules: [...] }
 * where each rule is:
 *   { effect: 'allow'|'deny',
 *     subject:  { agent_ids?: string[], roles?: string[], all?: true },
 *     resource: { skill_ids?: string[], keys?: string[], source_types?: string[], all?: true } }
 * Rules are evaluated in order; first match wins, else defaultEffect.
 * (See nexus/governance/skill_policy.py.)
 */

import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { getActiveCompanyId } from '@/config';
import { Plus, Save, ShieldCheck, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';

interface PolicyRule {
  effect: 'allow' | 'deny';
  subjectAgentIds: string;
  subjectRoles: string;
  resourceKeys: string;
  resourceSourceTypes: string;
}

interface PolicyDoc {
  schemaVersion: number;
  revision: number;
  defaultEffect: 'allow' | 'deny';
  rules: Array<Record<string, unknown>>;
}

const csv = (s: string): string[] =>
  s.split(',').map((x) => x.trim()).filter(Boolean);

const join = (v: unknown): string => (Array.isArray(v) ? v.join(', ') : '');

/** Wire rule (backend shape) → editor row. */
function toRow(r: Record<string, any>): PolicyRule {
  const subject = r.subject ?? {};
  const resource = r.resource ?? {};
  return {
    effect: r.effect === 'deny' ? 'deny' : 'allow',
    subjectAgentIds: join(subject.agent_ids ?? subject.agent_id),
    subjectRoles: join(subject.roles ?? subject.role),
    resourceKeys: join(resource.keys ?? resource.key),
    resourceSourceTypes: join(resource.source_types ?? resource.source_type),
  };
}

/** Editor row → wire rule (backend shape). Empty clauses match everything. */
function toWire(row: PolicyRule): Record<string, unknown> {
  const subject: Record<string, unknown> = {};
  if (row.subjectAgentIds.trim()) subject.agent_ids = csv(row.subjectAgentIds);
  if (row.subjectRoles.trim()) subject.roles = csv(row.subjectRoles);
  const resource: Record<string, unknown> = {};
  if (row.resourceKeys.trim()) resource.keys = csv(row.resourceKeys);
  if (row.resourceSourceTypes.trim()) resource.source_types = csv(row.resourceSourceTypes);
  return {
    effect: row.effect,
    subject: Object.keys(subject).length ? subject : { all: true },
    resource: Object.keys(resource).length ? resource : { all: true },
  };
}

const inputCls =
  'w-full px-2 py-1 bg-[#0C0C0E] border border-white/[0.1] rounded text-white text-xs focus:outline-none focus:border-[#FFB020]';

export function SkillPolicyPanel() {
  const [defaultEffect, setDefaultEffect] = useState<'allow' | 'deny'>('allow');
  const [revision, setRevision] = useState(0);
  const [rules, setRules] = useState<PolicyRule[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    apiClient
      .get<PolicyDoc>(`/api/v1/companies/${getActiveCompanyId()}/skill-policy`)
      .then((doc) => {
        setDefaultEffect(doc.defaultEffect === 'deny' ? 'deny' : 'allow');
        setRevision(doc.revision ?? 0);
        setRules((doc.rules ?? []).map(toRow));
      })
      .catch((err) => console.error('Failed to load skill policy', err))
      .finally(() => setLoading(false));
  }, []);

  const addRule = () =>
    setRules((prev) => [
      ...prev,
      { effect: 'deny', subjectAgentIds: '', subjectRoles: '', resourceKeys: '', resourceSourceTypes: '' },
    ]);

  const removeRule = (i: number) => setRules((prev) => prev.filter((_, idx) => idx !== i));

  const updateRule = (i: number, patch: Partial<PolicyRule>) =>
    setRules((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));

  const handleSave = async () => {
    setSaving(true);
    try {
      const doc = await apiClient.put<PolicyDoc>(
        `/api/v1/companies/${getActiveCompanyId()}/skill-policy`,
        { defaultEffect, rules: rules.map(toWire) },
      );
      setRevision(doc.revision ?? revision + 1);
      setSavedAt(Date.now());
    } catch (err) {
      console.error('Failed to save skill policy', err);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="p-8 text-center text-xs font-mono text-[#6B6B6E]">Loading policy…</div>;
  }

  return (
    <Card
      header={
        <div className="flex items-center justify-between w-full">
          <span className="text-xs font-mono font-medium uppercase text-[#F2F1EE] flex items-center gap-2">
            <ShieldCheck size={14} className="text-[#FFB020]" /> Skill Access Policy · rev {revision}
          </span>
          <Button variant="primary" size="xs" icon={<Save size={13} />} loading={saving} onClick={handleSave}>
            Save Policy
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-xs font-sans">
        <p className="text-[11px] text-[#6B6B6E] leading-relaxed">
          Rules are evaluated top to bottom; the first match wins. If no rule matches, the
          default effect applies. Comma-separate multiple values; glob patterns (e.g.
          <code className="text-[#FFB020]"> secret-*</code>) are supported. Leave a clause empty
          to match everything.
        </p>

        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono text-gray-400 uppercase">Default effect</span>
          <div className="flex items-center gap-1">
            {(['allow', 'deny'] as const).map((eff) => (
              <button
                key={eff}
                type="button"
                onClick={() => setDefaultEffect(eff)}
                className="px-3 py-1 rounded text-[11px] font-mono border cursor-pointer transition-colors"
                style={{
                  borderColor: defaultEffect === eff ? (eff === 'allow' ? '#22C55E' : '#EF4444') : 'rgba(255,255,255,0.08)',
                  background: defaultEffect === eff ? (eff === 'allow' ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)') : 'transparent',
                  color: defaultEffect === eff ? (eff === 'allow' ? '#22C55E' : '#EF4444') : '#6B6B6E',
                }}
              >
                {eff}
              </button>
            ))}
          </div>
        </div>

        {/* Rules */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-gray-400 uppercase">Rules ({rules.length})</span>
            <Button variant="secondary" size="xs" icon={<Plus size={12} />} onClick={addRule}>
              Add Rule
            </Button>
          </div>

          {rules.length === 0 && (
            <div className="p-4 text-center text-[11px] font-mono text-[#6B6B6E] bg-[#101012] border border-white/[0.06] rounded-[6px]">
              No rules — every skill request falls through to the default effect.
            </div>
          )}

          {rules.map((rule, i) => (
            <div key={i} className="p-3 bg-[#101012] border border-white/[0.06] rounded-[6px] space-y-2">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-1">
                  <span className="text-[10px] font-mono text-[#6B6B6E] mr-1">#{i + 1}</span>
                  {(['allow', 'deny'] as const).map((eff) => (
                    <button
                      key={eff}
                      type="button"
                      onClick={() => updateRule(i, { effect: eff })}
                      className="px-2 py-0.5 rounded text-[10px] font-mono border cursor-pointer"
                      style={{
                        borderColor: rule.effect === eff ? (eff === 'allow' ? '#22C55E' : '#EF4444') : 'rgba(255,255,255,0.08)',
                        background: rule.effect === eff ? (eff === 'allow' ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)') : 'transparent',
                        color: rule.effect === eff ? (eff === 'allow' ? '#22C55E' : '#EF4444') : '#6B6B6E',
                      }}
                    >
                      {eff}
                    </button>
                  ))}
                </div>
                <button
                  onClick={() => removeRule(i)}
                  className="p-1 text-rose-400 hover:bg-white/[0.06] rounded cursor-pointer"
                  title="Remove rule"
                >
                  <Trash2 size={12} />
                </button>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="block text-[9px] font-mono text-[#6B6B6E] uppercase mb-0.5">Subject · agent ids</label>
                  <input className={inputCls} value={rule.subjectAgentIds} onChange={(e) => updateRule(i, { subjectAgentIds: e.target.value })} placeholder="all agents" />
                </div>
                <div>
                  <label className="block text-[9px] font-mono text-[#6B6B6E] uppercase mb-0.5">Subject · roles</label>
                  <input className={inputCls} value={rule.subjectRoles} onChange={(e) => updateRule(i, { subjectRoles: e.target.value })} placeholder="engineer, qa" />
                </div>
                <div>
                  <label className="block text-[9px] font-mono text-[#6B6B6E] uppercase mb-0.5">Resource · skill keys</label>
                  <input className={inputCls} value={rule.resourceKeys} onChange={(e) => updateRule(i, { resourceKeys: e.target.value })} placeholder="deploy-*, prod-secrets" />
                </div>
                <div>
                  <label className="block text-[9px] font-mono text-[#6B6B6E] uppercase mb-0.5">Resource · source types</label>
                  <input className={inputCls} value={rule.resourceSourceTypes} onChange={(e) => updateRule(i, { resourceSourceTypes: e.target.value })} placeholder="mcp, catalog" />
                </div>
              </div>
            </div>
          ))}
        </div>

        {savedAt && (
          <div className="text-[10px] font-mono text-emerald-400">
            Policy saved (revision {revision}). Applies to the next skill assignment.
          </div>
        )}
      </div>
    </Card>
  );
}
