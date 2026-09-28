/**
 * ChatManager — every employee conversation, keyed by company + agent + session.
 *
 * Requests capture their routing (conversation key, agent, session, request
 * ID) before they start and report back by that captured key, so a reply can
 * never land in whichever chat happens to be on screen. Which conversation is
 * selected, and whether the dock is visible, only controls what is shown.
 *
 * Each request is a durable server turn. Closing or refreshing the page only
 * disconnects: on load the manager asks for the conversation's unfinished
 * turns and re-attaches to them. Cancel is a server call, not a disconnect.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { attachTurn, cancelTurn, ChatStreamError, chatStreamPath, streamChat, type ChatReply, type StreamHandlers, type TurnInfo } from '@/api/chatStream';
import { getActiveCompanyId } from '@/config';
import type { Agent } from '@/types/agent';

export type ChatAgent = Pick<
  Agent,
  'id' | 'name' | 'title' | 'role' | 'adapter_type' | 'cli_backend' | 'model' | 'status' | 'capabilities' | 'budget_monthly_cents' | 'spent_monthly_cents'
>;

export interface ChatMessage {
  id: string;
  sender: 'user' | 'agent';
  text: string;
  timestamp: string;
  /** Which adapter/backend/model actually produced this reply. */
  via?: string;
}

export interface PendingRequest {
  requestId: string;
  prompt: string;
  startedAt: string;
  /** sending: not yet accepted; queued: stored, waiting for its slot; waiting: the employee is working. */
  phase: 'sending' | 'queued' | 'waiting';
  partial: string;
  /** The server turn, once the server has stored the prompt. */
  turn?: TurnInfo;
}

export interface Conversation {
  key: string;
  companyId: string;
  agentId: string;
  sessionId: string | null;
  agent: ChatAgent;
  messages: ChatMessage[];
  draft: string;
  pendingRequests: PendingRequest[];
  error: { message: string; prompt: string } | null;
  lastOutcome: 'completed' | 'failed' | null;
  unreadCount: number;
  lastActivityAt: string | null;
  adapterUsed: string | null;
  backendUsed: string | null;
  historyLoaded: boolean;
}

export interface ChatState {
  conversations: Record<string, Conversation>;
  /** Conversations shown as tabs in the dock, oldest first. */
  tabs: string[];
  activeKey: string | null;
  viewOpen: boolean;
}

export type ChatAction =
  | { type: 'OPEN_CONVERSATION'; companyId: string; agent: ChatAgent; sessionId: string | null; focus: boolean }
  | { type: 'SELECT_CONVERSATION'; key: string }
  | { type: 'SET_DRAFT'; key: string; draft: string }
  | { type: 'REQUEST_STARTED'; key: string; requestId: string; prompt: string; at: string }
  | { type: 'REQUEST_PROGRESS'; key: string; requestId: string; chunk?: string }
  | { type: 'REQUEST_ATTACHED'; key: string; requestId: string; turn: TurnInfo }
  | { type: 'REQUEST_RESUMED'; key: string; turn: TurnInfo; prompt: string; at: string }
  | { type: 'REQUEST_COMPLETED'; key: string; requestId: string; reply: ChatReply; at: string }
  | { type: 'REQUEST_FAILED'; key: string; requestId: string; message: string; cancelled: boolean; at: string }
  | { type: 'MARK_READ'; key: string }
  | { type: 'CLOSE_VIEW' }
  | { type: 'OPEN_VIEW' }
  | { type: 'HIDE_TAB'; key: string }
  | { type: 'HISTORY_LOADED'; key: string; messages: ChatMessage[] }
  | { type: 'APPEND_LOCAL'; key: string; message: ChatMessage }
  | { type: 'CLEAR'; key: string; message: ChatMessage };

/** Only what the chat needs, so remembered tabs stay small. */
export function toChatAgent(a: ChatAgent): ChatAgent {
  const { id, name, title, role, adapter_type, cli_backend, model, status, capabilities, budget_monthly_cents, spent_monthly_cents } = a;
  return { id, name, title, role, adapter_type, cli_backend, model, status, capabilities, budget_monthly_cents, spent_monthly_cents };
}

export function conversationKey(companyId: string, agentId: string, sessionId: string | null): string {
  return `${companyId}:${agentId}:${sessionId ?? 'default'}`;
}

export function executionLabel(e: { adapter_used?: string | null; backend_used?: string | null; model_used?: string | null }): string | undefined {
  const parts = [e.adapter_used, e.backend_used, e.model_used].filter(Boolean);
  return parts.length ? parts.join(' · ') : undefined;
}

export const initialChatState: ChatState = { conversations: {}, tabs: [], activeKey: null, viewOpen: false };

function isVisible(state: ChatState, key: string): boolean {
  return state.viewOpen && state.activeKey === key;
}

function update(state: ChatState, key: string, patch: (c: Conversation) => Partial<Conversation>): ChatState {
  const conv = state.conversations[key];
  if (!conv) return state;
  return { ...state, conversations: { ...state.conversations, [key]: { ...conv, ...patch(conv) } } };
}

function settle(state: ChatState, key: string, requestId: string, patch: (c: Conversation) => Partial<Conversation>): ChatState {
  const unseen = isVisible(state, key) ? 0 : 1;
  return update(state, key, (c) => ({
    pendingRequests: c.pendingRequests.filter((r) => r.requestId !== requestId),
    unreadCount: c.unreadCount + unseen,
    ...patch(c),
  }));
}

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case 'OPEN_CONVERSATION': {
      const key = conversationKey(action.companyId, action.agent.id, action.sessionId);
      const existing = state.conversations[key];
      const conv: Conversation = existing
        ? { ...existing, agent: action.agent }
        : {
            key,
            companyId: action.companyId,
            agentId: action.agent.id,
            sessionId: action.sessionId,
            agent: action.agent,
            messages: [],
            draft: '',
            pendingRequests: [],
            error: null,
            lastOutcome: null,
            unreadCount: 0,
            lastActivityAt: null,
            adapterUsed: null,
            backendUsed: null,
            historyLoaded: false,
          };
      const next = { ...state, conversations: { ...state.conversations, [key]: conv } };
      if (!action.focus) return next;
      return {
        ...next,
        tabs: next.tabs.includes(key) ? next.tabs : [...next.tabs, key],
        activeKey: key,
        viewOpen: true,
        conversations: { ...next.conversations, [key]: { ...conv, unreadCount: 0 } },
      };
    }
    case 'SELECT_CONVERSATION':
      if (!state.conversations[action.key]) return state;
      return update({ ...state, activeKey: action.key, viewOpen: true }, action.key, () => ({ unreadCount: 0 }));
    case 'SET_DRAFT':
      return update(state, action.key, () => ({ draft: action.draft }));
    case 'REQUEST_STARTED':
      return update(state, action.key, (c) => ({
        messages: [...c.messages, { id: `local-${action.requestId}`, sender: 'user', text: action.prompt, timestamp: action.at }],
        pendingRequests: [
          ...c.pendingRequests,
          { requestId: action.requestId, prompt: action.prompt, startedAt: action.at, phase: 'sending', partial: '' },
        ],
        draft: '',
        error: null,
        lastOutcome: null,
        lastActivityAt: action.at,
      }));
    case 'REQUEST_PROGRESS':
      return update(state, action.key, (c) => ({
        pendingRequests: c.pendingRequests.map((r) =>
          r.requestId === action.requestId ? { ...r, phase: 'waiting', partial: r.partial + (action.chunk ?? '') } : r,
        ),
      }));
    case 'REQUEST_ATTACHED': {
      const { turn } = action;
      const phase = turn.status === 'queued' ? 'queued' : 'waiting';
      const localId = `local-${action.requestId}`;
      return update(state, action.key, (c) => ({
        pendingRequests: c.pendingRequests.map((r) => (r.requestId === action.requestId ? { ...r, turn, phase } : r)),
        // The prompt now has its server ID, so a history reload merges instead of duplicating it.
        messages: turn.prompt_message_id
          ? c.messages.map((m) => (m.id === localId ? { ...m, id: turn.prompt_message_id! } : m))
          : c.messages,
      }));
    }
    case 'REQUEST_RESUMED':
      return update(state, action.key, (c) =>
        c.pendingRequests.some((r) => r.turn?.turn_id === action.turn.turn_id)
          ? {}
          : {
              pendingRequests: [
                ...c.pendingRequests,
                {
                  requestId: action.turn.turn_id,
                  prompt: action.prompt,
                  startedAt: action.at,
                  phase: action.turn.status === 'queued' ? 'queued' : 'waiting',
                  partial: '',
                  turn: action.turn,
                },
              ],
            },
      );
    case 'REQUEST_COMPLETED': {
      const { reply } = action;
      return settle(state, action.key, action.requestId, (c) => ({
        messages: c.messages.some((m) => m.id === reply.message.id)
          ? c.messages
          : [...c.messages, { ...reply.message, via: executionLabel(reply) }],
        lastOutcome: 'completed',
        lastActivityAt: action.at,
        adapterUsed: reply.adapter_used ?? c.adapterUsed,
        backendUsed: reply.backend_used ?? c.backendUsed,
      }));
    }
    case 'REQUEST_FAILED': {
      const prompt = state.conversations[action.key]?.pendingRequests.find((r) => r.requestId === action.requestId)?.prompt ?? '';
      return settle(state, action.key, action.requestId, (c) =>
        action.cancelled
          ? {
              messages: [...c.messages, { id: `cancel-${action.requestId}`, sender: 'agent', text: 'Request cancelled.', timestamp: action.at }],
              lastActivityAt: action.at,
            }
          : { error: { message: action.message, prompt }, lastOutcome: 'failed', lastActivityAt: action.at },
      );
    }
    case 'MARK_READ':
      return update(state, action.key, () => ({ unreadCount: 0 }));
    case 'CLOSE_VIEW':
      return { ...state, viewOpen: false };
    case 'OPEN_VIEW':
      return state.activeKey ? update({ ...state, viewOpen: true }, state.activeKey, () => ({ unreadCount: 0 })) : state;
    case 'HIDE_TAB': {
      // The transcript and any running request stay; reopening restores the tab.
      const tabs = state.tabs.filter((k) => k !== action.key);
      const activeKey = state.activeKey === action.key ? (tabs[tabs.length - 1] ?? null) : state.activeKey;
      return { ...state, tabs, activeKey, viewOpen: state.viewOpen && activeKey !== null };
    }
    case 'HISTORY_LOADED':
      // Anything already in the transcript was typed after the fetch began; keep it.
      return update(state, action.key, (c) => {
        const known = new Set(action.messages.map((m) => m.id));
        return { historyLoaded: true, messages: [...action.messages, ...c.messages.filter((m) => !known.has(m.id))] };
      });
    case 'APPEND_LOCAL':
      return update(state, action.key, (c) => ({ messages: [...c.messages, action.message] }));
    case 'CLEAR':
      return update(state, action.key, () => ({ messages: [action.message], error: null, lastOutcome: null }));
    default:
      return state;
  }
}

// ── Provider ──────────────────────────────────────────────────────────

const STORAGE_KEY = 'nexus.chat.tabs';

interface StoredTabs {
  tabs: Array<{ companyId: string; sessionId: string | null; agent: ChatAgent }>;
  activeKey: string | null;
}

function restore(): ChatState {
  let state = initialChatState;
  try {
    const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? 'null') as StoredTabs | null;
    for (const t of stored?.tabs ?? []) {
      state = chatReducer(state, { type: 'OPEN_CONVERSATION', companyId: t.companyId, agent: t.agent, sessionId: t.sessionId, focus: true });
    }
    if (stored?.activeKey && state.conversations[stored.activeKey]) state = { ...state, activeKey: stored.activeKey };
  } catch {
    return initialChatState;
  }
  // Restored tabs start collapsed: the page opens as it was, the dock does not pop up.
  return { ...state, viewOpen: false };
}

export interface ChatManager {
  state: ChatState;
  dispatch: (action: ChatAction) => void;
  /** Open (and show) the agent's conversation, loading its history once. */
  open: (agent: ChatAgent, sessionId?: string | null) => string;
  /** Register a conversation without showing it in the dock. */
  ensure: (agent: ChatAgent, sessionId: string | null) => string;
  /** Fetch the server transcript and unfinished turns once, and re-attach to those turns. */
  loadHistory: (key: string) => void;
  /** Returns false when this conversation already has a request in flight. */
  send: (key: string, prompt: string) => boolean;
  cancel: (requestId: string) => void;
  retry: (key: string) => void;
}

const ChatManagerContext = createContext<ChatManager | null>(null);

/** A transcript row as the server sends it, with the labels of the run that wrote it. */
type ServerMessage = ChatMessage & { adapter_used?: string | null; backend_used?: string | null; model_used?: string | null };

let requestSeq = 0;
function newRequestId(): string {
  requestSeq += 1;
  return globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${requestSeq}`;
}

export function ChatManagerProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, undefined, restore);
  const queryClient = useQueryClient();
  const controllers = useRef(new Map<string, AbortController>());
  const turns = useRef(new Map<string, TurnInfo>());
  const cancelling = useRef(new Set<string>());
  const stop = useCallback((requestId: string) => {
    const turn = turns.current.get(requestId);
    if (!turn) return;
    // Only a confirmed cancel ends the request here; if the call fails the turn is still running.
    cancelTurn(turn.session_id, turn.turn_id)
      .then(() => controllers.current.get(requestId)?.abort())
      .catch(() => cancelling.current.delete(requestId));
  }, []);
  // Checked synchronously, so a double click cannot start two turns in one chat.
  const busy = useRef(new Set<string>());
  const stateRef = useRef(state);
  stateRef.current = state;

  useEffect(() => {
    try {
      const stored: StoredTabs = {
        tabs: state.tabs.map((k) => {
          const c = state.conversations[k]!;
          return { companyId: c.companyId, sessionId: c.sessionId, agent: c.agent };
        }),
        activeKey: state.activeKey,
      };
      localStorage.setItem(STORAGE_KEY, JSON.stringify(stored));
    } catch {
      // Storage unavailable: tabs simply are not remembered.
    }
  }, [state.tabs, state.activeKey, state.conversations]);

  // Follow one request to its end and settle it under its captured key.
  const follow = useCallback(
    (key: string, requestId: string, sessionId: string | null, run: (h: StreamHandlers) => Promise<ChatReply>) => {
      const controller = new AbortController();
      busy.current.add(key);
      controllers.current.set(requestId, controller);
      run({
        signal: controller.signal,
        onOpen: () => dispatch({ type: 'REQUEST_PROGRESS', key, requestId }),
        onTurn: (turn) => {
          turns.current.set(requestId, turn);
          dispatch({ type: 'REQUEST_ATTACHED', key, requestId, turn });
          if (cancelling.current.has(requestId)) stop(requestId);
        },
        onChunk: (chunk) => dispatch({ type: 'REQUEST_PROGRESS', key, requestId, chunk }),
      })
        .then((reply) => dispatch({ type: 'REQUEST_COMPLETED', key, requestId, reply, at: new Date().toISOString() }))
        .catch((err: unknown) =>
          dispatch({
            type: 'REQUEST_FAILED',
            key,
            requestId,
            message: err instanceof Error ? err.message : 'Failed to send message.',
            cancelled: controller.signal.aborted || (err instanceof ChatStreamError && err.code === 'TURN_CANCELLED'),
            at: new Date().toISOString(),
          }),
        )
        .finally(() => {
          busy.current.delete(key);
          controllers.current.delete(requestId);
          turns.current.delete(requestId);
          cancelling.current.delete(requestId);
          if (sessionId) {
            queryClient.invalidateQueries({
              predicate: ({ queryKey }) => queryKey[0] === 'sessions' && queryKey[2] === sessionId,
            });
          }
        });
    },
    [queryClient, stop],
  );

  // Each conversation loads its transcript and unfinished turns the first time
  // it is shown, then re-attaches to those turns: this is how a refreshed page
  // gets its pending requests back. Session chats read their transcript from
  // the session timeline, so only their turns are fetched here.
  const loading = useRef(new Set<string>());
  const loadHistory = useCallback(
    (key: string) => {
      const conv = stateRef.current.conversations[key];
      if (!conv || conv.historyLoaded || loading.current.has(key)) return;
      loading.current.add(key);
      const { agentId, sessionId } = conv;
      const history: Promise<ServerMessage[]> = sessionId
        ? Promise.resolve([])
        : apiClient.get<ServerMessage[]>(`/api/v1/agents/${agentId}/chat`).catch(() => []);
      const pending = apiClient
        .get<TurnInfo[]>(sessionId ? `/api/v1/agent-sessions/${sessionId}/turns` : `/api/v1/agents/${agentId}/chat/turns`, { pending: true })
        .catch((): TurnInfo[] => []);
      Promise.all([history, pending])
        .then(([messages, turnList]) => {
          const list = Array.isArray(messages) ? messages : [];
          dispatch({
            type: 'HISTORY_LOADED',
            key,
            messages: list.map((m) => ({ id: m.id, sender: m.sender, text: m.text, timestamp: m.timestamp, via: executionLabel(m) })),
          });
          const followed = new Set([...turns.current.values()].map((t) => t.turn_id));
          for (const turn of Array.isArray(turnList) ? turnList : []) {
            if (!turn.turn_id || !turn.session_id || followed.has(turn.turn_id)) continue;
            const prompt = list.find((m) => m.id === turn.prompt_message_id)?.text ?? '';
            dispatch({ type: 'REQUEST_RESUMED', key, turn, prompt, at: new Date().toISOString() });
            turns.current.set(turn.turn_id, turn);
            follow(key, turn.turn_id, sessionId, (h) => attachTurn(turn, h));
          }
        })
        .finally(() => loading.current.delete(key));
    },
    [follow],
  );

  const ensure = useCallback((agent: ChatAgent, sessionId: string | null) => {
    const companyId = getActiveCompanyId();
    dispatch({ type: 'OPEN_CONVERSATION', companyId, agent: toChatAgent(agent), sessionId, focus: false });
    return conversationKey(companyId, agent.id, sessionId);
  }, []);

  const open = useCallback((agent: ChatAgent, sessionId: string | null = null) => {
    const companyId = getActiveCompanyId();
    dispatch({ type: 'OPEN_CONVERSATION', companyId, agent: toChatAgent(agent), sessionId, focus: true });
    return conversationKey(companyId, agent.id, sessionId);
  }, []);

  const send = useCallback(
    (key: string, prompt: string) => {
      const conv = stateRef.current.conversations[key];
      const text = prompt.trim();
      if (!conv || !text || busy.current.has(key)) return false;
      // Routing is fixed here; nothing below reads the current selection.
      const { agentId, sessionId } = conv;
      const requestId = newRequestId();
      dispatch({ type: 'REQUEST_STARTED', key, requestId, prompt: text, at: new Date().toISOString() });
      follow(key, requestId, sessionId, (h) => streamChat(chatStreamPath(agentId, sessionId), text, requestId, h));
      return true;
    },
    [follow],
  );

  // Cancel the server turn, then stop listening. A request whose turn is not
  // known yet is cancelled as soon as the server names it.
  const cancel = useCallback(
    (requestId: string) => {
      cancelling.current.add(requestId);
      stop(requestId);
    },
    [stop],
  );

  const retry = useCallback(
    (key: string) => {
      const prompt = stateRef.current.conversations[key]?.error?.prompt;
      if (prompt) send(key, prompt);
    },
    [send],
  );

  const value = useMemo(
    () => ({ state, dispatch, open, ensure, loadHistory, send, cancel, retry }),
    [state, open, ensure, loadHistory, send, cancel, retry],
  );
  return <ChatManagerContext.Provider value={value}>{children}</ChatManagerContext.Provider>;
}

export function useChatManager(): ChatManager {
  const manager = useContext(ChatManagerContext);
  if (!manager) throw new Error('useChatManager must be used inside ChatManagerProvider');
  return manager;
}
