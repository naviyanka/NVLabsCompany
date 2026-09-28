import { apiClient, apiUrl, legacyCompanyHeaders, postHeaders } from '@/api/client';

export interface ChatReply {
  message: { id: string; sender: 'user' | 'agent'; text: string; timestamp: string };
  model_used?: string | null;
  tokens_used?: number;
  adapter_used?: string | null;
  backend_used?: string | null;
  execution_id?: string | null;
  turn_id?: string | null;
  session_id?: string | null;
}

/** The server's view of a turn that has not finished yet. */
export interface TurnInfo {
  turn_id: string;
  session_id: string;
  agent_id?: string;
  status: string;
  prompt_message_id?: string | null;
  retry_after?: number | null;
}

export class ChatStreamError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = 'ChatStreamError';
  }
}

/** The endpoint a conversation posts to: an explicit session, or the agent's default one. */
export function chatStreamPath(agentId: string, sessionId: string | null): string {
  return sessionId
    ? `/api/v1/sessions/${sessionId}/messages/stream`
    : `/api/v1/agents/${agentId}/chat/stream`;
}

const turnPath = (sessionId: string, turnId: string) => `/api/v1/agent-sessions/${sessionId}/turns/${turnId}`;

/** Durable cancel: whichever server runs the turn stops it. */
export function cancelTurn(sessionId: string, turnId: string): Promise<TurnInfo> {
  return apiClient.post<TurnInfo>(`${turnPath(sessionId, turnId)}/cancel`);
}

function detailMessage(body: unknown, fallback: string): { text: string; code?: string } {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string') return { text: detail };
  if (detail && typeof detail === 'object') {
    const d = detail as { message?: string; code?: string };
    return { text: d.message ?? fallback, code: d.code };
  }
  return { text: fallback };
}

export interface StreamHandlers {
  signal: AbortSignal;
  /** The server accepted the turn and is now running it. */
  onOpen?: () => void;
  /** The server stored the prompt as this turn. */
  onTurn?: (turn: TurnInfo) => void;
  onChunk?: (text: string) => void;
}

/** Reconnects after a dropped stream before giving up; the turn itself keeps running. */
const RECONNECTS = 5;

/** The first reconnect is immediate; later ones back off a second at a time. */
function pause(attempt: number, signal: AbortSignal): Promise<void> {
  if (attempt <= 1) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, 1000 * (attempt - 1));
    signal.addEventListener('abort', () => {
      clearTimeout(timer);
      reject(new DOMException('Aborted', 'AbortError'));
    });
  });
}

type Event = { type?: string; text?: string; code?: string; status?: number } & Partial<ChatReply> & Partial<TurnInfo>;

/** Read one SSE response. Resolves with the reply, or null when the stream ended early. */
async function readEvents(
  body: ReadableStream<Uint8Array>,
  onEvent: (event: Event) => void,
  onId: (id: string) => void,
): Promise<ChatReply | null> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) return null;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed.startsWith('id: ')) onId(trimmed.slice(4));
      if (!trimmed.startsWith('data: ')) continue;
      const data = trimmed.slice(6);
      if (data === '[DONE]') continue;
      let event: Event;
      try {
        event = JSON.parse(data);
      } catch {
        continue;
      }
      if (event.type === 'error') throw new ChatStreamError(event.text ?? 'Chat error', event.status, event.code);
      if (event.type === 'done' && event.message) return event as ChatReply;
      onEvent(event);
    }
  }
}

/**
 * Follow one turn to its reply. The first request is `start`; after a dropped
 * connection it re-attaches to the turn's event stream with Last-Event-ID, so
 * the text already shown is not repeated and the turn is never run twice.
 */
async function follow(
  start: (lastEventId: string | null) => Promise<Response>,
  known: TurnInfo | null,
  { signal, onOpen, onTurn, onChunk }: StreamHandlers,
): Promise<ChatReply> {
  let turn = known;
  // Set from inside the event callback, so TypeScript must not narrow it to null.
  let lastId = null as string | null;
  for (let attempt = 0; ; attempt++) {
    await pause(attempt, signal);
    let response: Response;
    try {
      response = turn && attempt > 0
        ? await fetch(apiUrl(`${turnPath(turn.session_id, turn.turn_id)}/events`), {
            headers: { ...legacyCompanyHeaders(), ...(lastId ? { 'Last-Event-ID': lastId } : {}) },
            credentials: 'include',
            signal,
          })
        : await start(lastId);
    } catch (err) {
      if (signal.aborted || attempt >= RECONNECTS) throw err;
      continue;
    }
    if (!response.ok || !response.body) {
      if (response.status >= 500 && attempt < RECONNECTS) continue;
      const body = await response.json().catch(() => null);
      const { text, code } = detailMessage(body, `Request failed (${response.status})`);
      throw new ChatStreamError(text, response.status, code);
    }
    onOpen?.();
    try {
      const reply = await readEvents(
        response.body,
        (event) => {
          if (event.type === 'chunk' && event.text) onChunk?.(event.text);
          else if (event.type === 'turn' && event.turn_id && event.session_id) {
            turn = event as TurnInfo;
            onTurn?.(turn);
          }
        },
        (id) => (lastId = id),
      );
      if (reply) return reply;
    } catch (err) {
      if (err instanceof ChatStreamError || signal.aborted) throw err;
    }
    if (attempt >= RECONNECTS) {
      throw new ChatStreamError('Lost the connection. The turn keeps running; its reply appears after a refresh.');
    }
  }
}

/**
 * POST one prompt to an SSE chat endpoint and resolve with the final reply.
 * `requestId` is the idempotency key: a retried POST attaches to the same
 * turn. Aborting `signal` only disconnects; the turn keeps running on the
 * server. Use `cancelTurn` to stop it.
 */
export function streamChat(path: string, prompt: string, requestId: string, handlers: StreamHandlers): Promise<ChatReply> {
  return follow(
    (lastEventId) =>
      fetch(apiUrl(path), {
        method: 'POST',
        headers: { ...postHeaders(), 'Idempotency-Key': requestId, ...(lastEventId ? { 'Last-Event-ID': lastEventId } : {}) },
        credentials: 'include',
        body: JSON.stringify({ prompt, request_id: requestId }),
        signal: handlers.signal,
      }),
    null,
    handlers,
  );
}

/** Re-attach to a turn that is already running, for example after a page refresh. */
export function attachTurn(turn: TurnInfo, handlers: StreamHandlers): Promise<ChatReply> {
  return follow(
    () =>
      fetch(apiUrl(`${turnPath(turn.session_id, turn.turn_id)}/events`), {
        headers: legacyCompanyHeaders(),
        credentials: 'include',
        signal: handlers.signal,
      }),
    turn,
    handlers,
  );
}
