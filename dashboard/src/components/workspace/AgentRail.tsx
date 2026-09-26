import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Bot, Plus } from 'lucide-react';

import { listAgents } from '@/api/agents';
import { createSession, listSessions, sessionKeys, type Session } from '@/api/sessions';
import { getActiveCompanyId } from '@/config';
import { describeError } from './describeError';

interface AgentRailProps {
  agentId: string | null;
  sessionId: string | null;
  onSelectAgent: (agentId: string) => void;
  onSelectSession: (session: Session) => void;
}

/** Explorer rail: the company's agents, and the selected agent's sessions. */
export function AgentRail({ agentId, sessionId, onSelectAgent, onSelectSession }: AgentRailProps) {
  const agents = useQuery({ queryKey: ['agents', getActiveCompanyId()], queryFn: listAgents });
  const sessions = useQuery({
    queryKey: sessionKeys.list(agentId ?? undefined),
    queryFn: () => listSessions(agentId!),
    enabled: !!agentId,
  });

  const queryClient = useQueryClient();
  const create = useMutation({
    mutationFn: () => createSession(agentId!),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: ['sessions', 'list'] });
      onSelectSession(created);
    },
  });

  return (
    <aside
      aria-label="Agents and sessions"
      className="w-64 shrink-0 flex flex-col min-h-0 border-r border-white/[0.08] bg-[#0C0C0E]"
    >
      <div className="px-3 py-2.5 text-[11px] font-mono text-[#6B6B6E] uppercase border-b border-white/[0.08]">
        Agents
      </div>
      <div className="flex-1 overflow-y-auto">
        {agents.isLoading && <p className="p-3 text-xs text-[#6B6B6E]">Loading agents…</p>}
        {agents.error && <p className="p-3 text-xs text-red-400">{describeError(agents.error)}</p>}
        {agents.data?.length === 0 && <p className="p-3 text-xs text-[#6B6B6E]">No agents yet.</p>}
        <ul>
          {agents.data?.map((agent) => {
            const selected = agent.id === agentId;
            return (
              <li key={agent.id}>
                <button
                  type="button"
                  aria-current={selected ? 'true' : undefined}
                  onClick={() => onSelectAgent(agent.id)}
                  className={`w-full flex items-center gap-2 px-3 py-2 text-left text-xs ${
                    selected ? 'bg-white/[0.06] text-[#F2F1EE]' : 'text-[#9C9C9F] hover:bg-white/[0.03]'
                  }`}
                >
                  <Bot size={14} className={selected ? 'text-[#FFB020]' : ''} />
                  <span className="truncate flex-1">{agent.name}</span>
                  <span className="text-[10px] font-mono text-[#6B6B6E]">{agent.status}</span>
                </button>
                {selected && (
                  <div className="pl-6 pr-2 pb-2">
                    <button
                      type="button"
                      onClick={() => create.mutate()}
                      disabled={create.isPending}
                      className="w-full flex items-center gap-1.5 px-2 py-1 text-[11px] text-[#38BDF8] hover:bg-white/[0.03] rounded disabled:opacity-50"
                    >
                      <Plus size={12} /> New session
                    </button>
                    {create.error && (
                      <p className="px-2 text-[10px] text-red-400">{describeError(create.error)}</p>
                    )}
                    {sessions.isLoading && <p className="px-2 text-[10px] text-[#6B6B6E]">Loading…</p>}
                    {sessions.error && (
                      <p className="px-2 text-[10px] text-red-400">{describeError(sessions.error)}</p>
                    )}
                    <ul aria-label="Sessions">
                      {sessions.data?.map((s) => (
                        <li key={s.id}>
                          <button
                            type="button"
                            aria-current={s.id === sessionId ? 'true' : undefined}
                            onClick={() => onSelectSession(s)}
                            className={`w-full flex items-center justify-between gap-2 px-2 py-1 text-left text-[11px] rounded ${
                              s.id === sessionId
                                ? 'bg-[#FFB020]/10 text-[#F2F1EE]'
                                : 'text-[#9C9C9F] hover:bg-white/[0.03]'
                            }`}
                          >
                            <span className="truncate">{s.title || `Session ${s.id.slice(0, 8)}`}</span>
                            <span className="text-[10px] font-mono text-[#6B6B6E]">{s.status}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}
