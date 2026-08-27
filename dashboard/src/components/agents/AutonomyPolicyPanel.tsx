/**
 * AutonomyPolicyPanel — per-action autonomy tier editor for an agent.
 *
 * Mirrors the backend contract in `nexus/tools/autonomy.py`:
 * `autonomy_policy` is `{ action_type: 1 | 2 | 3, spend_above_cents?: number }`.
 * Levels: L1 run silently · L2 run + notify · L3 create approval + block.
 * Persists via PUT /api/v1/agents/{id}.
 */

import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { Card } from '@/components/common/Card';
import { Bell, Save, ShieldCheck, ShieldAlert } from 'lucide-react';
import { useMemo, useState } from 'react';

/** Action buckets the backend classifies tool calls into (autonomy.py). */
const ACTION_TYPES: { key: string; label: string; hint: string }[] = [
  { key: 'read', label: 'Read', hint: 'Read files, query data, fetch — lowest risk' },
  { key: 'write_file', label: 'Write File', hint: 'Create/edit/save/commit/upload files' },
  { key: 'execute_code', label: 'Execute Code', hint: 'Shell, bash, run code, eval, terminal' },
  { key: 'send_external_message', label: 'Send External', hint: 'Email, Slack, SMS, webhook, publish' },
  { key: 'delete', label: 'Delete', hint: 'Delete/remove/destroy/drop/purge' },
  { key: 'spend', label: 'Spend', hint: 'Calls above the spend threshold below' },
];

const SPEND_THRESHOLD_KEY = 'spend_above_cents';

const LEVELS: { value: number; label: string; desc: string; color: string; icon: typeof ShieldCheck }[] = [
  { value: 1, label: 'L1 · Auto', desc: 'Run, no ceremony', color: '#22C55E', icon: ShieldCheck },
  { value: 2, label: 'L2 · Notify', desc: 'Run, but notify an operator', color: '#FFB020', icon: Bell },
  { value: 3, label: 'L3 · Approve', desc: 'Create approval and block until approved', color: '#EF4444', icon: ShieldAlert },
];

type Policy = Record<string, number>;

export function AutonomyPolicyPanel({
  agentId,
  policy,
  onSaved,
}: {
  agentId: string;
  policy: Record<string, unknown> | null | undefined;
  onSaved?: (next: Record<string, unknown>) => void;
}) {
  // Normalize the incoming policy into per-action levels + spend threshold.
  const initial = useMemo(() => {
    const p = (policy ?? {}) as Record<string, unknown>;
    const levels: Policy = {};
    for (const { key } of ACTION_TYPES) {
      const raw = Number(p[key]);
      levels[key] = raw >= 1 && raw <= 3 ? raw : 1;
    }
    const spend = Number(p[SPEND_THRESHOLD_KEY]);
    return { levels, spendAboveCents: Number.isFinite(spend) && spend > 0 ? spend : 0 };
  }, [policy]);

  const [levels, setLevels] = useState<Policy>(initial.levels);
  const [spendAboveCents, setSpendAboveCents] = useState<number>(initial.spendAboveCents);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  const dirty = useMemo(() => {
    if (spendAboveCents !== initial.spendAboveCents) return true;
    return ACTION_TYPES.some(({ key }) => levels[key] !== initial.levels[key]);
  }, [levels, spendAboveCents, initial]);

  const setLevel = (action: string, level: number) =>
    setLevels((prev) => ({ ...prev, [action]: level }));

  const handleSave = async () => {
    setSaving(true);
    const next: Record<string, unknown> = { ...levels };
    if (spendAboveCents > 0) next[SPEND_THRESHOLD_KEY] = spendAboveCents;
    try {
      await apiClient.put(`/api/v1/agents/${agentId}`, { autonomy_policy: next });
      setSavedAt(Date.now());
      onSaved?.(next);
    } catch (err) {
      console.error('Failed to save autonomy policy', err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      header={
        <div className="flex items-center justify-between w-full">
          <span className="text-xs font-mono font-medium uppercase text-[#F2F1EE]">
            Per-Action Autonomy Policy
          </span>
          <Button
            variant="primary"
            size="xs"
            icon={<Save size={13} />}
            loading={saving}
            disabled={!dirty}
            onClick={handleSave}
          >
            Save Policy
          </Button>
        </div>
      }
    >
      <div className="space-y-4 text-xs font-sans">
        <p className="text-[11px] text-[#6B6B6E] leading-relaxed">
          Every tool call is classified into one of these action buckets, then gated by the
          level you set. L1 runs silently, L2 runs and notifies, L3 files an approval and
          blocks until a human authorizes it.
        </p>

        <div className="space-y-2">
          {ACTION_TYPES.map((action) => (
            <div
              key={action.key}
              className="flex items-center justify-between gap-3 p-2.5 bg-[#101012] border border-white/[0.06] rounded-[6px]"
            >
              <div className="min-w-0">
                <div className="text-xs font-medium text-[#F2F1EE]">{action.label}</div>
                <div className="text-[10px] text-[#6B6B6E] truncate">{action.hint}</div>
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {LEVELS.map((lvl) => {
                  const active = levels[action.key] === lvl.value;
                  const Icon = lvl.icon;
                  return (
                    <button
                      key={lvl.value}
                      type="button"
                      onClick={() => setLevel(action.key, lvl.value)}
                      title={lvl.desc}
                      className="px-2 py-1 rounded-[4px] text-[10px] font-mono flex items-center gap-1 border transition-colors cursor-pointer"
                      style={{
                        borderColor: active ? lvl.color : 'rgba(255,255,255,0.08)',
                        background: active ? lvl.color + '1A' : 'transparent',
                        color: active ? lvl.color : '#6B6B6E',
                      }}
                    >
                      <Icon size={11} />
                      {lvl.label}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Spend threshold */}
        <div className="flex items-center justify-between gap-3 p-2.5 bg-[#101012] border border-white/[0.06] rounded-[6px]">
          <div className="min-w-0">
            <div className="text-xs font-medium text-[#F2F1EE]">Spend threshold</div>
            <div className="text-[10px] text-[#6B6B6E]">
              A spending call at or below this amount is treated as a plain read (not gated).
            </div>
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <span className="text-[10px] font-mono text-[#6B6B6E]">$</span>
            <input
              type="number"
              min={0}
              step="0.01"
              value={spendAboveCents ? (spendAboveCents / 100).toString() : ''}
              onChange={(e) => {
                const dollars = parseFloat(e.target.value);
                setSpendAboveCents(Number.isFinite(dollars) && dollars > 0 ? Math.round(dollars * 100) : 0);
              }}
              placeholder="0.00"
              className="w-24 bg-[#0C0C0E] border border-white/[0.1] rounded-[4px] px-2 py-1 text-[#F2F1EE] text-xs text-right focus:outline-none focus:border-[#FFB020]"
            />
          </div>
        </div>

        {savedAt && !dirty && (
          <div className="text-[10px] font-mono text-emerald-400">
            Policy saved. Applies to the agent's next tool calls.
          </div>
        )}
      </div>
    </Card>
  );
}
