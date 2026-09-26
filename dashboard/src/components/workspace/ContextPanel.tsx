import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { listAgents } from '@/api/agents';
import {
  getSessionEffectiveTools,
  getTimeline,
  getUsage,
  listSessionBindings,
  sessionKeys,
  type Session,
} from '@/api/sessions';
import { getActiveCompanyId } from '@/config';
import { describeError } from './describeError';

// Outcomes of the server's access check (nexus.tools.access).
const OUTCOME_COLORS: Record<string, string> = {
  allowed: 'text-emerald-400',
  would_deny: 'text-amber-400',
  denied: 'text-red-400',
};

interface ContextPanelProps {
  agentId: string | null;
  session: Session | null;
}

/**
 * What the server says about the current selection. Nothing here is editable:
 * tool access and bindings are decided server-side and only displayed.
 */
export function ContextPanel({ agentId, session }: ContextPanelProps) {
  const sid = session?.id ?? '';
  const agents = useQuery({ queryKey: ['agents', getActiveCompanyId()], queryFn: listAgents });
  const usage = useQuery({ queryKey: sessionKeys.usage(sid), queryFn: () => getUsage(sid), enabled: !!sid });
  const tools = useQuery({
    queryKey: sessionKeys.tools(sid),
    queryFn: () => getSessionEffectiveTools(sid),
    enabled: !!sid,
  });
  const bindings = useQuery({
    queryKey: sessionKeys.bindings(sid),
    queryFn: () => listSessionBindings(sid),
    enabled: !!sid,
  });
  // Same key as the chat tab, so this is one request, not two.
  const timeline = useQuery({ queryKey: sessionKeys.timeline(sid), queryFn: () => getTimeline(sid), enabled: !!sid });

  const agent = agents.data?.find((a) => a.id === agentId);
  const activity = (timeline.data ?? []).filter((item) => item.type !== 'message').slice(-10).reverse();
  const worktree = session?.metadata?.worktree;

  return (
    <aside
      aria-label="Context"
      className="w-72 shrink-0 overflow-y-auto border-l border-white/[0.08] bg-[#0C0C0E] text-xs"
    >
      <Section title="Session">
        {session ? (
          <Fields
            rows={[
              ['Status', session.status],
              ['Adapter', session.adapter_type],
              ['Model', session.model],
              ['Connection', session.llm_connection_id?.slice(0, 8)],
              ['Events', String(session.event_seq)],
              ['Last activity', new Date(session.last_activity_at).toLocaleString()],
            ]}
          />
        ) : (
          <Empty>No session selected.</Empty>
        )}
      </Section>

      <Section title="Agent">
        {agent ? (
          <Fields rows={[['Name', agent.name], ['Role', agent.role], ['Status', agent.status], ['Model', agent.model]]} />
        ) : (
          <Empty>{agentId ? 'Agent not found.' : 'No agent selected.'}</Empty>
        )}
      </Section>

      {session && (
        <>
          <Section title="Usage">
            {usage.error ? (
              <ErrorText error={usage.error} />
            ) : (
              <Fields
                rows={[
                  ['Cost', usage.data ? `$${(usage.data.cost_cents / 100).toFixed(2)}` : '…'],
                  ['Tokens in', usage.data ? String(usage.data.input_tokens) : '…'],
                  ['Tokens out', usage.data ? String(usage.data.output_tokens) : '…'],
                ]}
              />
            )}
          </Section>

          <Section title="Tools">
            {tools.error && <ErrorText error={tools.error} />}
            {tools.data?.length === 0 && <Empty>No tools in scope.</Empty>}
            <ul aria-label="Tools" className="space-y-1">
              {tools.data?.map((t) => (
                <li key={`${t.connection_id}:${t.tool_name}`} className="flex justify-between gap-2">
                  <span className="truncate text-[#F2F1EE]">{t.tool_name}</span>
                  <span className={`font-mono ${OUTCOME_COLORS[t.outcome] ?? 'text-red-400'}`}>
                    {t.outcome}
                  </span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="MCP bindings">
            {bindings.error && <ErrorText error={bindings.error} />}
            {bindings.data?.length === 0 && <Empty>No bindings.</Empty>}
            <ul aria-label="MCP bindings" className="space-y-1">
              {bindings.data?.map((b) => (
                <li key={b.id} className="flex justify-between gap-2 text-[#9C9C9F]">
                  <span className="font-mono">{b.connection_id.slice(0, 8)}</span>
                  <span>
                    {b.target_type} · {b.status}
                  </span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Activity">
            {timeline.error && <ErrorText error={timeline.error} />}
            {timeline.data && activity.length === 0 && <Empty>No tool calls or usage yet.</Empty>}
            <ul aria-label="Activity" className="space-y-1">
              {activity.map((item) => (
                <li key={item.id} className="flex justify-between gap-2 text-[#9C9C9F]">
                  <span className="truncate">
                    {item.type === 'tool_call' ? String(item.tool_name) : item.type}
                  </span>
                  <span className="font-mono text-[#6B6B6E]">{String(item.status ?? item.model ?? '')}</span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Git / worktree">
            {typeof worktree === 'string' ? (
              <Fields rows={[['Worktree', worktree]]} />
            ) : (
              <Empty>No worktree attached to this session.</Empty>
            )}
          </Section>
        </>
      )}
    </aside>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="px-3 py-2.5 border-b border-white/[0.06]">
      <h2 className="mb-1.5 text-[11px] font-mono text-[#6B6B6E] uppercase">{title}</h2>
      {children}
    </section>
  );
}

function Fields({ rows }: { rows: Array<[string, string | null | undefined]> }) {
  return (
    <dl className="space-y-0.5">
      {rows.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-2">
          <dt className="text-[#6B6B6E]">{label}</dt>
          <dd className="truncate text-[#F2F1EE]">{value || '—'}</dd>
        </div>
      ))}
    </dl>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-[#6B6B6E]">{children}</p>;
}

function ErrorText({ error }: { error: unknown }) {
  return <p className="text-red-400">{describeError(error)}</p>;
}
