/**
 * TriggersPanel — manage proactive agent triggers.
 *
 * Wraps the backend trigger API:
 *   GET  /api/v1/companies/{id}/triggers
 *   POST /api/v1/companies/{id}/triggers
 *   PUT  /api/v1/triggers/{id}            (activate/deactivate/edit)
 *   POST /api/v1/triggers/{id}/fire       (manual fire)
 *   GET  /api/v1/triggers/{id}/executions (history)
 *
 * Config keys per trigger_type (see runtime/scheduler.compute_next_fire):
 *   cron     -> { cron_expression }
 *   interval -> { interval_seconds }
 *   once     -> { scheduled_at }  (ISO datetime)
 *   webhook  -> { secret }        (does not auto-fire)
 *   on_message -> {}              (event-driven)
 */

import { apiClient } from '@/api/client';
import { Button } from '@/components/common/Button';
import { getActiveCompanyId } from '@/config';
import { Clock, Play, Plus, Power, Radio, Webhook, X, Zap } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

interface Trigger {
  id: string;
  agent_id: string;
  trigger_type: string;
  name: string;
  description?: string | null;
  config?: Record<string, unknown> | null;
  is_active: boolean;
  last_fired_at?: string | null;
  next_fire_at?: string | null;
  created_at: string;
}

interface TriggerExecution {
  id: string;
  trigger_id: string;
  status: string;
  error?: string | null;
  started_at: string;
  completed_at?: string | null;
}

const TRIGGER_TYPES = [
  { value: 'cron', label: 'Cron', icon: Clock, hint: 'Fire on a cron schedule' },
  { value: 'interval', label: 'Interval', icon: Zap, hint: 'Fire every N seconds' },
  { value: 'once', label: 'Once', icon: Clock, hint: 'Fire once at a specific time' },
  { value: 'webhook', label: 'Webhook', icon: Webhook, hint: 'Fire on an inbound signed webhook' },
  { value: 'on_message', label: 'On Message', icon: Radio, hint: 'Fire on an inbound message event' },
] as const;

function typeIcon(type: string) {
  return TRIGGER_TYPES.find((t) => t.value === type)?.icon ?? Zap;
}

export function TriggersPanel({ agents }: { agents: { id: string; name: string }[] }) {
  const [triggers, setTriggers] = useState<Trigger[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [executionsFor, setExecutionsFor] = useState<Trigger | null>(null);
  const [executions, setExecutions] = useState<TriggerExecution[]>([]);

  const loadTriggers = async () => {
    try {
      const res = await apiClient.get<Trigger[]>(
        `/api/v1/companies/${getActiveCompanyId()}/triggers`,
      );
      setTriggers(Array.isArray(res) ? res : []);
    } catch (err) {
      console.error('Failed to load triggers', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadTriggers();
  }, []);

  const toggleActive = async (t: Trigger) => {
    try {
      await apiClient.put(`/api/v1/triggers/${t.id}`, { is_active: !t.is_active });
      setTriggers((prev) => prev.map((x) => (x.id === t.id ? { ...x, is_active: !x.is_active } : x)));
    } catch (err) {
      console.error('Failed to toggle trigger', err);
    }
  };

  const fireNow = async (t: Trigger) => {
    try {
      await apiClient.post(`/api/v1/triggers/${t.id}/fire`, {});
      setTriggers((prev) =>
        prev.map((x) => (x.id === t.id ? { ...x, last_fired_at: new Date().toISOString() } : x)),
      );
    } catch (err) {
      console.error('Failed to fire trigger', err);
    }
  };

  const openExecutions = async (t: Trigger) => {
    setExecutionsFor(t);
    setExecutions([]);
    try {
      const res = await apiClient.get<TriggerExecution[]>(`/api/v1/triggers/${t.id}/executions`);
      setExecutions(Array.isArray(res) ? res : []);
    } catch (err) {
      console.error('Failed to load executions', err);
    }
  };

  return (
    <div className="space-y-4 font-sans">
      <div className="flex items-center justify-between">
        <div className="text-xs font-mono text-[#6B6B6E] uppercase">
          Proactive Triggers ({triggers.length})
        </div>
        <Button variant="primary" size="sm" icon={<Plus size={14} />} onClick={() => setShowCreate(true)}>
          New Trigger
        </Button>
      </div>

      {loading ? (
        <div className="p-8 text-center text-xs font-mono text-[#6B6B6E]">Loading triggers…</div>
      ) : triggers.length === 0 ? (
        <div className="p-8 text-center bg-[#141416] border border-white/[0.08] rounded-[10px] text-xs font-mono text-[#6B6B6E]">
          No triggers yet. Create one to wake an agent on a schedule, webhook, or event.
        </div>
      ) : (
        <div className="space-y-2">
          {triggers.map((t) => {
            const Icon = typeIcon(t.trigger_type);
            const agentName = agents.find((a) => a.id === t.agent_id)?.name || t.agent_id.slice(0, 8);
            return (
              <div
                key={t.id}
                className="p-3.5 bg-[#141416] border border-white/[0.08] rounded-[8px] flex items-center justify-between gap-3"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span
                    className="w-8 h-8 rounded flex items-center justify-center shrink-0 border"
                    style={{
                      background: t.is_active ? 'rgba(34,197,94,0.1)' : 'rgba(255,255,255,0.04)',
                      borderColor: t.is_active ? 'rgba(34,197,94,0.3)' : 'rgba(255,255,255,0.08)',
                    }}
                  >
                    <Icon size={15} className={t.is_active ? 'text-emerald-400' : 'text-[#6B6B6E]'} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-xs font-medium text-[#F2F1EE] truncate">{t.name}</div>
                    <div className="text-[10px] font-mono text-[#6B6B6E]">
                      {t.trigger_type} · agent {agentName}
                      {t.next_fire_at && (
                        <>
                          {' '}· next {new Date(t.next_fire_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                        </>
                      )}
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-1.5 shrink-0">
                  <button
                    onClick={() => openExecutions(t)}
                    className="px-2 py-1 rounded text-[10px] font-mono text-cyan-400 hover:bg-white/[0.06] cursor-pointer"
                  >
                    History
                  </button>
                  <Button variant="ghost" size="xs" icon={<Play size={12} className="text-[#FFB020]" />} onClick={() => fireNow(t)}>
                    Fire
                  </Button>
                  <button
                    onClick={() => toggleActive(t)}
                    title={t.is_active ? 'Deactivate' : 'Activate'}
                    className="p-1.5 rounded cursor-pointer hover:bg-white/[0.06]"
                  >
                    <Power size={14} className={t.is_active ? 'text-emerald-400' : 'text-[#6B6B6E]'} />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showCreate && (
        <CreateTriggerModal
          agents={agents}
          onClose={() => setShowCreate(false)}
          onCreated={(t) => {
            setTriggers((prev) => [t, ...prev]);
            setShowCreate(false);
          }}
        />
      )}

      {executionsFor && (
        <ExecutionsModal
          trigger={executionsFor}
          executions={executions}
          onClose={() => setExecutionsFor(null)}
        />
      )}
    </div>
  );
}

/* ── Create modal ── */
function CreateTriggerModal({
  agents,
  onClose,
  onCreated,
}: {
  agents: { id: string; name: string }[];
  onClose: () => void;
  onCreated: (t: Trigger) => void;
}) {
  const [name, setName] = useState('');
  const [agentId, setAgentId] = useState(agents[0]?.id ?? '');
  const [triggerType, setTriggerType] = useState<string>('cron');
  const [cronExpr, setCronExpr] = useState('0 9 * * *');
  const [intervalSeconds, setIntervalSeconds] = useState(3600);
  const [scheduledAt, setScheduledAt] = useState('');
  const [secret, setSecret] = useState('');
  const [saving, setSaving] = useState(false);

  const config = useMemo(() => {
    switch (triggerType) {
      case 'cron':
        return { cron_expression: cronExpr };
      case 'interval':
        return { interval_seconds: intervalSeconds };
      case 'once':
        return scheduledAt ? { scheduled_at: new Date(scheduledAt).toISOString() } : {};
      case 'webhook':
        return secret ? { secret } : {};
      default:
        return {};
    }
  }, [triggerType, cronExpr, intervalSeconds, scheduledAt, secret]);

  const canSave = name.trim() && agentId;

  const handleCreate = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const created = await apiClient.post<Trigger>(
        `/api/v1/companies/${getActiveCompanyId()}/triggers`,
        {
          agent_id: agentId,
          trigger_type: triggerType,
          name: name.trim(),
          config,
          is_active: true,
        },
      );
      onCreated(created);
    } catch (err) {
      console.error('Failed to create trigger', err);
    } finally {
      setSaving(false);
    }
  };

  const inputCls =
    'w-full px-3 py-2 bg-[#0C0C0E] border border-white/[0.1] rounded text-white text-xs focus:outline-none focus:border-[#FFB020]';
  const labelCls = 'block text-[11px] font-mono text-gray-400 uppercase mb-1';

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-[#141416] border border-white/[0.12] rounded-[12px] p-5 w-[440px] max-h-[90vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-white">New Trigger</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white cursor-pointer">
            <X size={16} />
          </button>
        </div>

        <div className="space-y-3">
          <div>
            <label className={labelCls}>Name</label>
            <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning standup wake" />
          </div>

          <div>
            <label className={labelCls}>Agent</label>
            <select className={inputCls} value={agentId} onChange={(e) => setAgentId(e.target.value)}>
              {agents.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          <div>
            <label className={labelCls}>Type</label>
            <select className={inputCls} value={triggerType} onChange={(e) => setTriggerType(e.target.value)}>
              {TRIGGER_TYPES.map((t) => (
                <option key={t.value} value={t.value}>{t.label} — {t.hint}</option>
              ))}
            </select>
          </div>

          {triggerType === 'cron' && (
            <div>
              <label className={labelCls}>Cron expression</label>
              <input className={`${inputCls} font-mono`} value={cronExpr} onChange={(e) => setCronExpr(e.target.value)} placeholder="0 9 * * *" />
              <p className="text-[10px] text-[#6B6B6E] mt-1">min hour day month weekday — e.g. 0 9 * * * = 9am daily</p>
            </div>
          )}

          {triggerType === 'interval' && (
            <div>
              <label className={labelCls}>Interval (seconds)</label>
              <input type="number" min={1} className={inputCls} value={intervalSeconds} onChange={(e) => setIntervalSeconds(Math.max(1, Number(e.target.value)))} />
            </div>
          )}

          {triggerType === 'once' && (
            <div>
              <label className={labelCls}>Fire at</label>
              <input type="datetime-local" className={inputCls} value={scheduledAt} onChange={(e) => setScheduledAt(e.target.value)} />
            </div>
          )}

          {triggerType === 'webhook' && (
            <div>
              <label className={labelCls}>Signing secret (HMAC)</label>
              <input className={inputCls} value={secret} onChange={(e) => setSecret(e.target.value)} placeholder="shared secret for signature verification" />
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-5 pt-3 border-t border-white/[0.08]">
          <Button variant="secondary" size="sm" onClick={onClose}>Cancel</Button>
          <Button variant="primary" size="sm" loading={saving} disabled={!canSave} onClick={handleCreate}>
            Create Trigger
          </Button>
        </div>
      </div>
    </div>
  );
}

/* ── Executions modal ── */
function ExecutionsModal({
  trigger,
  executions,
  onClose,
}: {
  trigger: Trigger;
  executions: TriggerExecution[];
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4" onClick={onClose}>
      <div
        className="bg-[#141416] border border-white/[0.12] rounded-[12px] p-5 w-[520px] max-h-[80vh] overflow-y-auto shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-medium text-white">Executions — {trigger.name}</h3>
          <button onClick={onClose} className="p-1 text-gray-400 hover:text-white cursor-pointer">
            <X size={16} />
          </button>
        </div>

        {executions.length === 0 ? (
          <div className="p-6 text-center text-xs font-mono text-[#6B6B6E]">No executions recorded yet.</div>
        ) : (
          <div className="space-y-2">
            {executions.map((ex) => (
              <div key={ex.id} className="p-2.5 bg-[#101012] border border-white/[0.06] rounded-[6px] flex items-center justify-between text-xs font-mono">
                <div>
                  <span
                    className={
                      ex.status === 'completed'
                        ? 'text-emerald-400'
                        : ex.status === 'failed'
                          ? 'text-rose-400'
                          : 'text-[#FFB020]'
                    }
                  >
                    {ex.status}
                  </span>
                  {ex.error && <span className="text-rose-400 ml-2">{ex.error.slice(0, 60)}</span>}
                </div>
                <span className="text-[#6B6B6E]">
                  {new Date(ex.started_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
