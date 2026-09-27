import { useEffect } from 'react';
import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import {
  getTimeline,
  sessionKeys,
  terminateSession,
  type Session,
  type TimelineItem,
} from '@/api/sessions';
import { describeError } from './describeError';
import { getActiveCompanyId } from '@/config';
import { conversationKey, useChatManager } from '@/contexts/ChatManagerContext';

export const WORKSPACE_TABS = ['chat', 'files', 'canvas', 'terminal', 'review'] as const;
export type WorkspaceTab = (typeof WORKSPACE_TABS)[number];

const TAB_LABELS: Record<WorkspaceTab, string> = {
  chat: 'Chat',
  files: 'Files',
  canvas: 'Canvas',
  terminal: 'Terminal',
  review: 'Git / Review',
};

/** The workspace surfaces; shared by the session pane and the canvas. */
export function WorkspaceTabs({ tab, onTab }: { tab: WorkspaceTab; onTab: (tab: WorkspaceTab) => void }) {
  return (
    <nav role="tablist" className="flex gap-1 px-3 border-b border-white/[0.08]">
      {WORKSPACE_TABS.map((t) => (
        <button
          key={t}
          type="button"
          role="tab"
          aria-selected={t === tab}
          onClick={() => onTab(t)}
          className={`px-3 py-2 text-xs border-b-2 ${
            t === tab ? 'border-[#FFB020] text-[#F2F1EE]' : 'border-transparent text-[#6B6B6E]'
          }`}
        >
          {TAB_LABELS[t]}
        </button>
      ))}
    </nav>
  );
}

// A UI hint only: the server refuses turns on an ended session regardless.
const OPEN_STATUSES = ['active', 'idle'];

interface SessionPaneProps {
  sessionId: string | null;
  session: UseQueryResult<Session>;
  tab: WorkspaceTab;
  onTab: (tab: WorkspaceTab) => void;
  onClear: () => void;
}

/** Main workspace: the selected session, with one tab per surface. */
export function SessionPane({ sessionId, session, tab, onTab, onClear }: SessionPaneProps) {
  const queryClient = useQueryClient();
  const terminate = useMutation({
    mutationFn: () => terminateSession(sessionId!),
    onSettled: () =>
      queryClient.invalidateQueries({
        predicate: ({ queryKey }) =>
          queryKey[0] === 'sessions' && (queryKey[1] === 'list' || queryKey[2] === sessionId),
      }),
  });

  if (!sessionId) {
    return (
      <section className="flex-1 flex flex-col items-center justify-center gap-2 text-sm text-[#6B6B6E]">
        Select an agent and a session, or start a new one.
        <button type="button" onClick={() => onTab('canvas')} className="text-xs text-[#38BDF8]">
          Open canvas
        </button>
      </section>
    );
  }
  if (session.isLoading) {
    return <section className="flex-1 p-4 text-sm text-[#6B6B6E]">Loading session…</section>;
  }
  if (session.error || !session.data) {
    return (
      <section role="alert" className="flex-1 p-4 text-sm">
        <p className="text-red-400">Session unavailable: {describeError(session.error)}</p>
        <button type="button" onClick={onClear} className="mt-2 text-xs text-[#38BDF8]">
          Clear selection
        </button>
      </section>
    );
  }

  const s = session.data;
  const open = OPEN_STATUSES.includes(s.status);
  return (
    <section aria-label="Session" className="flex-1 flex flex-col min-w-0 min-h-0">
      <header className="flex items-center justify-between gap-2 px-4 py-2.5 border-b border-white/[0.08]">
        <div className="min-w-0">
          <h1 className="text-sm text-[#F2F1EE] truncate">{s.title || `Session ${s.id.slice(0, 8)}`}</h1>
          <p className="text-[10px] font-mono text-[#6B6B6E]">
            {s.status} · {s.adapter_type ?? '—'} · {s.model ?? '—'}
          </p>
        </div>
        {open && (
          <button
            type="button"
            onClick={() => terminate.mutate()}
            disabled={terminate.isPending}
            className="text-[11px] px-2 py-1 border border-white/[0.08] rounded text-[#9C9C9F] hover:text-red-400 disabled:opacity-50"
          >
            Terminate
          </button>
        )}
      </header>
      {terminate.error && (
        <p className="px-4 py-1 text-[11px] text-red-400">{describeError(terminate.error)}</p>
      )}
      <WorkspaceTabs tab={tab} onTab={onTab} />
      {tab === 'chat' ? (
        <ChatTab key={s.id} session={s} open={open} />
      ) : (
        <div role="tabpanel" className="flex-1 p-6 text-sm text-[#6B6B6E]">
          {TAB_LABELS[tab]} for this session arrives in a later phase.
        </div>
      )}
    </section>
  );
}

function ChatTab({ session, open }: { session: Session; open: boolean }) {
  const sessionId = session.id;
  const timeline = useQuery({
    queryKey: sessionKeys.timeline(sessionId),
    queryFn: () => getTimeline(sessionId),
  });
  // Draft, pending turn, cancel and error live in the chat manager under this
  // session's key, so they survive switching sessions and never leak between them.
  const chat = useChatManager();
  const { ensure } = chat;
  const key = conversationKey(getActiveCompanyId(), session.agent_id, sessionId);
  useEffect(() => {
    ensure(
      {
        id: session.agent_id,
        name: 'Agent',
        title: '',
        role: '',
        adapter_type: session.adapter_type ?? '',
        cli_backend: null,
        model: session.model ?? '',
        status: 'idle',
        capabilities: [],
        budget_monthly_cents: 0,
        spent_monthly_cents: 0,
      },
      sessionId,
    );
  }, [ensure, session.agent_id, session.adapter_type, session.model, sessionId]);
  const conv = chat.state.conversations[key];
  const draft = conv?.draft ?? '';
  const pending = conv?.pendingRequests ?? [];
  const setDraft = (value: string) => chat.dispatch({ type: 'SET_DRAFT', key, draft: value });

  const messages = (timeline.data ?? []).filter((item) => item.type === 'message');
  return (
    <div role="tabpanel" className="flex-1 flex flex-col min-h-0">
      <ol aria-label="Messages" className="flex-1 overflow-y-auto p-4 space-y-3">
        {timeline.isLoading && <li className="text-xs text-[#6B6B6E]">Loading…</li>}
        {timeline.error && <li className="text-xs text-red-400">{describeError(timeline.error)}</li>}
        {timeline.data && messages.length === 0 && (
          <li className="text-xs text-[#6B6B6E]">No messages yet.</li>
        )}
        {messages.map((m) => (
          <Message key={m.id} item={m} />
        ))}
        {pending.map((r) => (
          <li key={r.requestId} aria-label="Pending request" className="flex items-center gap-2 text-xs text-[#6B6B6E]">
            <span className="flex-1 whitespace-pre-wrap">{r.partial || (r.phase === 'sending' ? 'Sending…' : 'Waiting for the agent…')}</span>
            <button type="button" onClick={() => chat.cancel(r.requestId)} className="text-[11px] text-red-400 hover:text-red-300">
              Cancel
            </button>
          </li>
        ))}
      </ol>
      <form
        className="flex gap-2 p-3 border-t border-white/[0.08]"
        onSubmit={(e) => {
          e.preventDefault();
          chat.send(key, draft);
        }}
      >
        <textarea
          aria-label="Message"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          disabled={!open}
          placeholder={open ? 'Message the agent…' : 'This session has ended.'}
          rows={2}
          className="flex-1 resize-none px-2.5 py-1.5 bg-[#141416] border border-white/[0.08] rounded-[6px] text-xs text-[#F2F1EE] focus:outline-none focus:border-[#FFB020] disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!open || pending.length > 0 || !draft.trim()}
          className="px-3 text-xs rounded-[6px] bg-[#FFB020] text-black disabled:opacity-40"
        >
          Send
        </button>
      </form>
      {conv?.error && (
        <p role="alert" className="px-3 pb-2 text-[11px] text-red-400">
          {conv.error.message}{' '}
          <button type="button" onClick={() => chat.retry(key)} className="text-[#FFB020]">
            Retry
          </button>
        </p>
      )}
    </div>
  );
}

function Message({ item }: { item: TimelineItem }) {
  const fromUser = item.sender === 'user';
  return (
    <li className={`max-w-[80%] ${fromUser ? 'ml-auto text-right' : ''}`}>
      <div
        className={`inline-block px-3 py-2 rounded-[10px] text-xs whitespace-pre-wrap text-left ${
          fromUser ? 'bg-[#FFB020]/10 text-[#F2F1EE]' : 'bg-[#101012] border border-white/[0.08] text-[#F2F1EE]'
        }`}
      >
        {String(item.text ?? '')}
      </div>
    </li>
  );
}
