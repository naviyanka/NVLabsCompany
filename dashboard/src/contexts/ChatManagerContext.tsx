/**
 * ChatManager — every employee conversation, keyed by company + agent + session.
 *
 * Requests capture their routing (conversation key, agent, session, request
 * ID) before they start and report back by that captured key, so a reply can
 * never land in whichever chat happens to be on screen. Which conversation is
 * selected, and whether the dock is visible, only controls what is shown.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef, type ReactNode } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { apiClient } from '@/api/client';
import { chatStreamPath, streamChat, type ChatReply } from '@/api/chatStream';
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
  /** sending: not yet accepted by the server; waiting: the employee is working. */
  phase: 'sending' | 'waiting';
  partial: string;
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
    case 'REQUEST_COMPLETED': {
      const { reply } = action;
      return settle(state, action.key, action.requestId, (c) => ({
        messages: [...c.messages, { ...reply.message, via: executionLabel(reply) }],
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
  /** Returns false when this conversation already has a request in flight. */
  /** Fetch an agent chat's server transcript once. */
  loadHistory: (key: string) => void;
  send: (key: string, prompt: string) => boolean;
  cancel: (requestId: string) => void;
  retry: (key: string) => void;
}

const ChatManagerContext = createContext<ChatManager | null>(null);

let requestSeq = 0;
function newRequestId(): string {
  requestSeq += 1;
  return globalThis.crypto?.randomUUID?.() ?? `req-${Date.now()}-${requestSeq}`;
}

export function ChatManagerProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(chatReducer, undefined, restore);
  const queryClient = useQueryClient();
  const controllers = useRef(new Map<string, AbortController>());
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

  // Agent chats load their transcript the first time they are shown. Session
  // chats read theirs from the session timeline instead.
  const loading = useRef(new Set<string>());
  const loadHistory = useCallback((key: string) => {
    const conv = stateRef.current.conversations[key];
    if (!conv || conv.historyLoaded || conv.sessionId || loading.current.has(key)) return;
    loading.current.add(key);
    apiClient
      .get<ChatMessage[]>(`/api/v1/agents/${conv.agentId}/chat`)
      .then((history) => dispatch({ type: 'HISTORY_LOADED', key, messages: Array.isArray(history) ? history : [] }))
      .catch(() => dispatch({ type: 'HISTORY_LOADED', key, messages: [] }))
      .finally(() => loading.current.delete(key));
  }, []);

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
      const controller = new AbortController();
      busy.current.add(key);
      controllers.current.set(requestId, controller);
      dispatch({ type: 'REQUEST_STARTED', key, requestId, prompt: text, at: new Date().toISOString() });

      streamChat(chatStreamPath(agentId, sessionId), text, {
        signal: controller.signal,
        onOpen: () => dispatch({ type: 'REQUEST_PROGRESS', key, requestId }),
        onChunk: (chunk) => dispatch({ type: 'REQUEST_PROGRESS', key, requestId, chunk }),
      })
        .then((reply) => dispatch({ type: 'REQUEST_COMPLETED', key, requestId, reply, at: new Date().toISOString() }))
        .catch((err: unknown) =>
          dispatch({
            type: 'REQUEST_FAILED',
            key,
            requestId,
            message: err instanceof Error ? err.message : 'Failed to send message.',
            cancelled: controller.signal.aborted,
            at: new Date().toISOString(),
          }),
        )
        .finally(() => {
          busy.current.delete(key);
          controllers.current.delete(requestId);
          if (sessionId) {
            queryClient.invalidateQueries({
              predicate: ({ queryKey }) => queryKey[0] === 'sessions' && queryKey[2] === sessionId,
            });
          }
        });
      return true;
    },
    [queryClient],
  );

  const cancel = useCallback((requestId: string) => controllers.current.get(requestId)?.abort(), []);

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
