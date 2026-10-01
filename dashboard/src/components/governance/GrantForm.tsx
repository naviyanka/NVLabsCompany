import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/common/Button';
import { apiClient } from '@/api/client';
import { BASE, Field, errorText, inputClass, type AgentRow } from './shared';

interface Cap { id: string; name: string; support: string; tool_name: string | null }
interface Created { status: string }

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function GrantForm({ agents }: { agents: AgentRow[] }) {
  const qc = useQueryClient();
  const [agentId, setAgentId] = useState('');
  const [tool, setTool] = useState('');
  const [effect, setEffect] = useState<'allow' | 'deny'>('allow');
  const [expires, setExpires] = useState('');
  const [session, setSession] = useState('');
  const [reason, setReason] = useState('');
  const [done, setDone] = useState('');

  const agent = agentId || agents[0]?.id || '';
  const caps = useQuery({
    queryKey: ['gov', 'access', agent],
    enabled: !!agent,
    queryFn: () => apiClient.get<{ capabilities: Cap[] }>(`${BASE}/agents/${agent}/effective-access`),
  });
  const tools = (caps.data?.capabilities ?? []).filter((c) => c.support === 'enforced' && c.tool_name);

  const expiry = expires ? new Date(expires) : null;
  const problems = [
    !tool && 'Choose a tool.',
    (!expiry || Number.isNaN(expiry.getTime())) ? 'Set an expiry.' : expiry.getTime() <= Date.now() && 'Expiry must be in the future.',
    session && !UUID.test(session.trim()) && 'Session scope must be a session id (UUID) or empty.',
    reason.trim().length < 5 && 'Give a reason of at least 5 characters.',
  ].filter(Boolean) as string[];

  const create = useMutation({
    mutationFn: () =>
      apiClient.post<Created>(`${BASE}/grants`, {
        agent_id: agent, tool_name: tool, effect, expires_at: expiry?.toISOString(),
        session_id: session.trim() || null, reason: reason.trim(),
      }),
    onSuccess: (g) => {
      setDone(`Grant created: ${g.status.replace(/_/g, ' ')}.`);
      setTool(''); setExpires(''); setSession(''); setReason('');
      qc.invalidateQueries({ queryKey: ['gov', 'grants'] });
    },
    onError: () => setDone(''),
  });

  return (
    <form aria-label="New temporary grant" className="mb-4 space-y-3 rounded-[8px] border border-white/[0.08] p-3"
      onSubmit={(e) => { e.preventDefault(); if (!problems.length) create.mutate(); }}>
      <h2 className="text-sm font-medium">New temporary grant</h2>
      <div className="flex flex-wrap gap-3">
        <Field name="Agent">
          <select className={inputClass} value={agent} onChange={(e) => { setAgentId(e.target.value); setTool(''); }}>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        </Field>
        <Field name="Tool" hint="One enforceable tool; patterns are not accepted.">
          <select className={inputClass} value={tool} onChange={(e) => setTool(e.target.value)}>
            <option value="">Select a tool</option>
            {tools.map((c) => <option key={c.id} value={c.tool_name!}>{c.name}</option>)}
          </select>
        </Field>
        <Field name="Effect">
          <select className={inputClass} value={effect} onChange={(e) => setEffect(e.target.value as 'allow' | 'deny')}>
            <option value="allow">Allow</option>
            <option value="deny">Deny</option>
          </select>
        </Field>
        <Field name="Expires" hint="Allow: up to 24 hours (read tools 7 days). Deny: up to 30 days.">
          <input type="datetime-local" className={inputClass} value={expires} onChange={(e) => setExpires(e.target.value)} />
        </Field>
        <Field name="Session scope (optional)" hint="Session is the only scope the engine can enforce.">
          <input className={inputClass} value={session} onChange={(e) => setSession(e.target.value)} />
        </Field>
        <Field name="Grant reason">
          <input className={inputClass} placeholder="Reason (at least 5 characters)" value={reason}
            onChange={(e) => setReason(e.target.value)} />
        </Field>
      </div>
      {problems.length > 0 && (
        <ul aria-label="Grant form problems" className="text-xs text-[#A8A8AB]">
          {problems.map((p) => <li key={p}>{p}</li>)}
        </ul>
      )}
      {create.error && <div role="alert" className="text-sm text-[#EF4444]">{errorText(create.error)}</div>}
      {done && <div role="status" className="text-sm">{done}</div>}
      <Button type="submit" size="sm" disabled={problems.length > 0} loading={create.isPending}>
        Create grant
      </Button>
    </form>
  );
}
